"""ET05 課程發布 Service（US3 / #204、#247、#273）。

發布是本模組唯一**有外部後果**的動作：通過檢核即產生邀請碼、觸發標籤自動邀請，並對
所有被帶入的學員寄信（FR-ET-US3-12）。檢核放過一門空課程，代價是全體學員收到通知去
看一門沒有內容的課——故 `publish()` **必定**重跑檢核，不因前端已呼叫過 `check()` 而略過。

## 發布的四件事

1. 狀態變更 + 首次發布時間
2. 產生邀請碼
3. **依受訓單位標籤帶入學員**（#247 追加，見下）
4. **對本次被帶入者逐人寄通知信**（#273 追加）

### 標籤帶入與寄信為何分兩次交付

#204 交付時把整個 FR-ET-US3-12 都推給 `ET-8`、只留接點。實測後發現那樣不成立：
課程掛了「護理師」標籤發布出去，具該標籤的學員**不會被帶進課程**，教師只能把 8 碼
邀請碼一個一個發。受訓單位標籤在發布流程裡等於沒有作用，而 `ET-4` 的我的課程對多數
學員永遠是空的——故 #247 先補上帶入本身。

當時未一併寄信，是為了避免臨時寄信邏輯與 `ET-8` 自己鋪的範本 / 寄送路徑打架。#273
落地後兩者收斂於 `app/et/notify/`（範本、params 組法、失敗不回滾皆在該處），本檔只
負責在正確的時點呼叫它。

仍不在本檔的：Email 邀請（另一種 `JOIN_SOURCE`，見 `app/et/invitation/`）。
（原本還有「`ET_INVITATION` 待加入清單（`ET-12`）」一項，已隨 #362 移除。）
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.et.audit_target import course_audit_payload
from app.et.catalog.pair import Pair
from app.et.common.dm_client import get_dm_document_client
from app.et.common.invitation_code import generate_invitation_code
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.publish_repository import EtPublishRepository
from app.et.course.publish_rules import PublishBlocker, evaluate_publish
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import (
    ensure_closable,
    ensure_owner,
    ensure_reopen_schedule,
    ensure_reopenable,
    is_effectively_closed,
)
from app.et.course.schemas import (
    CloseCourseReq,
    ContentUpdateResult,
    CourseStatusResult,
    PublishBlockerRow,
    PublishCheckResult,
    PublishResult,
)
from app.et.course.stage_apply import apply_stage
from app.et.course.stage_repository import EtCourseStageRepository
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE_TAG,
    KEPT_PAYLOAD_KEY,
    to_course_snapshot,
)
from app.et.course.stage_writer import EtCourseStageWriter
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.enrollment.tag_invite import EtTagInviteRepository
from app.et.notify.course_update import CourseUpdateMailer
from app.et.notify.mailer import CourseInviteMailer
from app.services import AuditLogService, ParamService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

#: 邀請碼長度之參數代碼（`data-model.md` §DP_PARAM）。單值參數，明細碼固定 `VALUE`。
_CODE_LENGTH_PARAM = "ET_INVITATION_CODE_LENGTH"
_DEFAULT_CODE_LENGTH = 8

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")


class EtPublishService:
    """課程發布檢核與狀態變更。"""

    def __init__(
        self,
        courses: EtCourseRepository | None = None,
        publish_repo: EtPublishRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
        tag_invite: EtTagInviteRepository | None = None,
        invite_mailer: CourseInviteMailer | None = None,
        stage: EtCourseStageRepository | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        course_update_mailer: CourseUpdateMailer | None = None,
    ) -> None:
        self._courses = courses or EtCourseRepository()
        self._publish = publish_repo or EtPublishRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()
        self._tag_invite = tag_invite or EtTagInviteRepository()
        self._invite_mailer = invite_mailer or CourseInviteMailer()
        self._stage = stage or EtCourseStageRepository()
        # #303 的通知從 `add_chapter` 移到「更新」當下（#631 PR 2a）——暫存模式下
        # 在新增當下寄信，信裡那句「課程新增了章節」對學員是假的。
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._course_update_mailer = course_update_mailer or CourseUpdateMailer()

    async def check(self, db: AsyncSession, course_id: int, *, actor_id: str) -> PublishCheckResult:
        """發布預檢：回傳缺漏清單，**不改變任何狀態**。

        讓前端能在按下發布之前就把缺漏標示出來（比照 #203 的逐欄回饋）。
        """
        course = await self._require_owned(db, course_id, actor_id)
        blockers = await self._evaluate_for_check(db, course)
        return PublishCheckResult(
            can_publish=not blockers,
            blockers=[PublishBlockerRow(code=b.code, message=b.message, target_id=b.target_id) for b in blockers],
        )

    async def publish(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> PublishResult:
        """發布課程：檢核 → 狀態變更 → 寫入首次發布時間 → 產生邀請碼。

        Raises:
            AppError: 409 `ET_PUBLISH_002` 課程非草稿狀態；
                422 `ET_PUBLISH_001` 檢核未通過（body 另帶 `blockers` 清單）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status != COURSE_DRAFT:
            # 已發布課程的後續編輯**即時生效、不需重新發布**（AC 28），故這裡不是
            # 「再發布一次」的入口。關閉 / 再開課屬 `ET-11`。
            raise AppError(status_code=409, detail="課程狀態不允許發布", error_code="ET_PUBLISH_002")

        blockers = await self._evaluate(db, course)
        if blockers:
            raise AppError(
                status_code=422,
                detail="發布條件未滿足",
                error_code="ET_PUBLISH_001",
                extra={
                    "blockers": [{"code": b.code, "message": b.message, "target_id": b.target_id} for b in blockers]
                },
            )

        code = await self._generate_code(db)
        new_version = await self._courses.mark_published(
            db, course_id, course.version, invitation_code=code, published_at=utcnow(), operator=operator
        )
        if new_version is None:
            # 版本在檢核與寫入之間被改動——此時整份檢核結果都已過時，回 409 讓教師
            # 重新載入再發一次，而不是用舊結果硬寫。
            raise AppError(
                status_code=409,
                detail="資料已被其他使用者修改，請重新載入後再試",
                error_code="ET_LOCK_001",
            )
        await self._log(db, operator.user_id, course_id, "發布課程")

        invited_ids = await self.enroll_audiences(db, course, operator=operator)

        return PublishResult(
            course_id=course_id,
            status=COURSE_PUBLISHED,
            invitation_code=code,
            version=new_version,
            invited_count=len(invited_ids),
        )

    async def update_published(
        self, db: AsyncSession, course_id: int, *, operator: OperatorInfo
    ) -> ContentUpdateResult:
        """「更新」已發布課程的內容：檢核暫存區 → 通過才整批生效（#631）。

        已發布課程的內容編輯原本即時生效，學員會看到教師編到一半的東西（0 題問卷被填答
        後永久凍結、0 題測驗讓項目永遠完成不了、改配分後總分不再是 100）。本端點是那些
        編輯**唯一的**生效入口。

        ## 檢核的是「即將生效的內容」

        `_evaluate` 的快照來自活表，而活表是**已生效版本**；這裡改由暫存樹組出同形的
        `CourseSnapshot`，再餵給**同一個** `evaluate_publish`。⛔ 不得另寫一份檢核——
        發布 / 關閉 / 再開課 / 更新四個動作共用同一組規則，各自複製必然分岔，而分岔的
        症狀是「更新擋下了發布會放行的課程」，沒有錯誤訊息。

        ## 未通過時活表一行都不會動

        檢核在 `apply_stage` 之前，且兩者同一個交易：未通過直接拋 `AppError`，連
        `_park_sort_orders` 都還沒跑。**AC 2「未通過時學員端維持上一版」靠的就是這件事**，
        不是靠補償或回滾。

        Raises:
            AppError: 404 `ET_COURSE_001` 查無課程；403 `ET_COURSE_002` 非擁有者；
                409 `ET_COURSE_010` 課程為草稿（草稿直接編輯後發布，不走暫存）；
                422 `ET_PUBLISH_001` 檢核未通過（body 另帶 `blockers`）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status == COURSE_DRAFT:
            # 草稿沒有學員，內容不需版本化——它的生效入口是「發布」。
            # ⛔ 不共用 `ET_PUBLISH_002`：下一步不同（那是「這門課不能發布」，這是
            # 「草稿不走這條路，請直接編輯後發布」），比照 `ET_COURSE_006` / `007`
            # 刻意不共用的理由。
            raise AppError(
                status_code=409,
                detail="草稿課程請直接編輯後發布，不需更新",
                error_code="ET_COURSE_010",
            )

        # 🔴 **先取行鎖再讀暫存樹**：這整段（讀 → 套用 → 清空）必須對同一門課序列化。
        # 教師雙擊或兩個分頁同時按下時，沒有鎖的話兩邊都會讀到完整的暫存樹並各自新增
        # 一份，活表出現重複的章節與題目。見 `lock_course` 的說明。
        await self._stage.lock_course(db, course_id)
        # ⚠️ 取鎖**之後**重讀課程列：上面的 `_require_owned` 讀的是鎖前快照。影響面小
        # （擁有權不可移轉、狀態只擋 DRAFT），但「先鎖再讀」才是這類流程的標準寫法。
        await db.refresh(course)
        nodes = await self._stage.load_tree(db, course_id)
        if not nodes and not await self._stage.has_stage(db, course_id):
            # 自上次更新以來**沒有開過編輯工作階段**。安全的 no-op——不跑檢核也不寫稽核：
            # 對一門內容未變的課程回 422 會讓教師以為自己弄壞了什麼。
            #
            # 🔴 判準是 `has_stage`（有沒有暫存列）而**不是** `nodes` 為空
            # （2026-10-18 code review MEDIUM 1）。兩者在「教師把內容全刪光」時分岔：
            # 那時暫存列都還在、只是全被軟刪，`nodes` 空而 `has_stage` 真。
            #
            # 用 `nodes` 判的話，刪光之後按「更新」會變成 no-op：教師既拿不到
            # `NO_CHAPTER` 的缺漏清單、刪除也永遠不會生效，而畫面上的課程是空的——
            # 他只剩「取消」一條路，而那會連同刪除一起放棄。
            return ContentUpdateResult(course_id=course_id, applied_count=0)

        # ⚠️ 起訖時間與受訓對象組數**由暫存樹自己帶**（#720）——它們已經不在活表那一側。
        # 只有 `status` 仍取活表：狀態轉換不走暫存。理由見 `to_course_snapshot` docstring。
        snapshot = to_course_snapshot(nodes, status=course.status)
        blockers = evaluate_publish(snapshot, obsolete_doc_ids=await self._obsolete_doc_ids(db, snapshot.doc_ids))
        if blockers:
            raise AppError(
                status_code=422,
                detail="更新條件未滿足",
                error_code="ET_PUBLISH_001",
                extra={
                    "blockers": [{"code": b.code, "message": b.message, "target_id": b.target_id} for b in blockers]
                },
            )

        # 🔴 **新增的章節在套用前先記下來**（#303 的通知延到此刻，#631 PR 2a）。
        #
        # 原本 `add_chapter` 當下就寄 `COURSE_UPDATE`，但暫存模式下那封信的內容是假的
        # ——信裡寫「課程新增了章節」，而學員此刻看不到任何變化。延到這裡才寄，信的
        # 內容才成立。
        #
        # ⚠️ 必須在 `apply_stage` **之前**取：套用後 `source_id` 就被填上了，分不出
        # 哪些是本次新增的。
        new_chapters = [
            str(n.payload.get("chapter_name") or "")
            for n in nodes
            if n.entity_type == ENTITY_CHAPTER and n.source_id is None
        ]
        # 🔴 受訓對象同理（#720）：**本次新增的配對**也要在套用前認出來。
        #
        # 判準同樣是 `source_id is None`——`_stage_basic` 刻意逐筆比對而非砍光重建，
        # 既有配對的 `SOURCE_ID` 因此保留著，只有真正新加的那幾組是 `None`。
        # 砍光重建的話這裡會把**全部**對象當成新增，整班重寄一次邀請信。
        new_pairs = {
            (n.payload["unit_tag_id"], n.payload["tag_id"])
            for n in nodes
            if n.entity_type == ENTITY_COURSE_TAG and n.source_id is None
        }
        # ⚠️ 「本次更新是否讓課程復活」要用**套用前**的活表值判定（#301 / #678）：
        # 套用之後 `course.open_end_at` 已是新值，再問一次只會恆為「沒復活」。
        was_effectively_closed = is_effectively_closed(
            status=course.status, open_end_at=course.open_end_at, now=utcnow()
        )

        stats = await apply_stage(db, course=course, nodes=nodes, operator=operator)
        await self._stage.clear(db, course_id, operator, stage_ids=[n.stage_id for n in nodes])

        # ⚠️ 完課狀態的「回退為進行中」**不在此寫入任何欄位**（#303 SA Q1 裁示 A，
        # 原文隨 `add_chapter` 的通知一起搬來）：`ET_ENROLLMENT.COMPLETION_STATUS` 只在
        # 加入課程時被寫過一次且**從未被讀**——所有讀取端自 #284 起一律以
        # `derive_completion_status(done, total)` 即時導出。新增項目使總數變大，狀態
        # 自動從「已完成」回到「進行中」；再寫一份欄位只會多一個會與導出值分歧的事實
        # 來源，而分歧的表現（清單說已完成、追蹤說進行中）沒有任何地方會察覺。
        #
        # ⭐ 這也是為什麼「完課回退延到更新時發生」不需要任何程式碼——它是**算出來的**，
        # 項目一進活表就自動成立。
        #
        # 一章一封，與原本「每次新增各寄一封」相同——只有**時機**改變。
        # ⛔ 不改成彙整成一封：那要改範本（`new_chapter_name` 是單數佔位），屬另一件事。
        # 📌 教師一次更新加了多章會收到多封，這是已知且接受的——若日後覺得吵，
        # 做法是改範本與 params，不是在這裡只寄第一封。
        #
        # 寄信失敗不回滾套用：`EtNotifier` 於唯一出口吞掉 `AppError`（見其 docstring）。
        if new_chapters:
            user_ids = await self._enrollments.enrolled_user_ids(db, course_id)
            for name in new_chapters:
                await self._course_update_mailer.send_course_update(
                    db, course=course, new_chapter_name=name, user_ids=user_ids
                )

        # 🔴 **受訓對象的帶入與邀請信（#720 從 `update_basic` 搬來）。**
        #
        # 三條規則原封不動，只有**時機**從「按儲存」改成「按更新」：
        #
        # - 期間已過亦視同關閉（#288）：否則「關閉期間不可邀請學員」（FR-ET-US11-07）
        #   會被整個繞過——Email 邀請已擋（409 `ET_INVITE_002`），但只要改成「幫課程
        #   加一組配對」，對應的學員就會被帶入並收到邀請信，而他進去什麼都不能做。
        # - 🔴 **復活時改依全部配對帶入**（#678）：延長期間讓視同關閉的課程復活，與再開課
        #   是同一件事——期間已過時新增的配對與新貼標的人都沒被帶入過（帶入與貼標追溯
        #   都排除視同關閉的課程），只補 `new_pairs` 會永久漏掉他們。全部配對已含本次
        #   新增者，故兩者擇一，不重複執行。
        # - 草稿不會走到這裡（上面已以 `ET_COURSE_010` 擋下）。
        #
        # ⚠️ 兩次 `is_effectively_closed` 的 `now` 都取當下，但讀的是**套用前後不同**的
        # `open_end_at`：前者在 `apply_stage` 之前算好，後者是套用之後的新值。
        if was_effectively_closed and not is_effectively_closed(
            status=course.status, open_end_at=course.open_end_at, now=utcnow()
        ):
            await self.enroll_audiences(db, course, operator=operator)
        elif (
            new_pairs
            and course.status == COURSE_PUBLISHED
            and not is_effectively_closed(status=course.status, open_end_at=course.open_end_at, now=utcnow())
        ):
            await self.backfill_new_tag_members(db, course, new_pairs, operator=operator)
        # 🔴 稽核描述要帶**刪除統計**，不能只有節點數。
        #
        # 這支端點沒有 request body，而它會經由 cascade 軟刪**學員的進度與作答紀錄**。
        # 只記 `len(nodes)` 的話，事後無法從 `DP_AUDIT_LOG` 區分「改了一個標題」與
        # 「刪掉五章連同全班進度」。只記型別與筆數，不記內容、不記學員識別。
        removed = "".join(f"，刪除 {k} {v} 筆" for k, v in sorted(stats.removed.items()))
        await self._log(db, operator.user_id, course_id, f"更新課程內容（{len(nodes)} 項）{removed}")
        return ContentUpdateResult(course_id=course_id, applied_count=len(nodes))

    async def discard_content(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """放棄尚未更新的編輯——教師按「取消」時走這條（#631，2026-10-16 使用者裁示）。

        ## 為什麼需要它

        暫存模式把「編輯」與「生效」拆成兩個時點之後，編輯工作階段就有兩個出口：按
        「更新」套用，或放棄。**原本只做了前者**——教師編到一半想整個丟掉、回到學員目前
        看到的版本，沒有任何入口（2026-10-16 security review 亦獨立指出）。

        ## 活表一行都不會動

        本端點只刪暫存列。學員看到的內容在整個編輯期間從未改變過，所以「放棄」不需要
        任何回滾——這正是暫存設計換來的性質。

        ## 草稿不適用

        草稿的章節與項目直接寫活表（沒有暫存表可清），按「取消」本來就不還原。回 409
        而非靜默成功：前端若誤把草稿導到這裡，要看得見。

        ⚠️ 取鎖後才刪：同時按下的「更新」可能正在套用，沒有鎖會把一半的內容送出去。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；409 `ET_COURSE_010` 草稿。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status == COURSE_DRAFT:
            raise AppError(
                status_code=409,
                detail="草稿課程的編輯直接生效，沒有可放棄的暫存內容",
                error_code="ET_COURSE_010",
            )
        await self._stage.lock_course(db, course_id)
        removed = await self._stage.discard(db, course_id)
        if removed:
            # 只記筆數：暫存列的內容從未對學員生效，記下來沒有稽核價值，且會把教師
            # 編輯中的文字寫進稽核表。
            await self._log(db, operator.user_id, course_id, f"放棄尚未更新的課程內容編輯（{removed} 項）")

    async def keep_edits(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """「保留編輯」：把暫存樹標記為**要留著**，不碰活表、不跑檢核（#720）。

        ## 🔴 它標記去留，不建立還原點

        設的是旗標，**不複製、不快照**。之後每一次編輯都就地改同一批暫存列，所以按下這顆
        鈕當下的那一版，在教師打下一個字的瞬間就沒了——沒有任何路徑回得去。

        ⇒ 鈕名因此**刻意不叫「儲存草稿」**（2026-10-20 裁示）：那個名字承諾一個回得去的
        版本，而這裡沒有。⛔ 不要改回去。若日後真要做成還原點，那是「按鈕時複製一份暫存
        樹」＋一個「還原」動作，不是改這裡的字。

        ⚠️ 與草稿狀態的「儲存草稿」是**兩回事**：那門課本身就是草稿，那顆鈕寫的是活表。

        ## 它不是「更新」的弱化版

        2026-10-19 裁示：已關閉課程的中間那顆鈕**不跑發布檢核**。理由是教師可能只是把
        半成品留著下次再弄——拿六項檢核擋他，等於逼他要嘛一次做完、要嘛整份丟掉。
        檢核留在「更新並重開課」那一顆，因為那顆才會讓學員看到。

        ⇒ 學員此刻唯讀回看的仍是**關閉前的內容**，一個字都沒變。

        ## 只有已關閉 / 視同關閉的課程有這顆鈕

        已發布課程刻意不設（同日裁示）：它的內容隨時對學員生效，「留著不發」這個狀態
        會讓教師以為自己已經處理完了。所以已發布的暫存樹恆無 `KEPT_PAYLOAD_KEY`、
        離開即丟（見 `discard_unkept`）。

        ⚠️ 旗標寫在課程節點上，經 `set_payload_flag`——它**刻意不遞增 `VERSION`**，
        否則教師按完這顆鈕手上的樂觀鎖令牌就過期，下一個動作無故 409。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；
                409 `ET_COURSE_011` 課程不是已關閉 / 視同關閉（草稿與運作中的已發布皆擋）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        await self._stage.lock_course(db, course_id)
        await db.refresh(course)
        # 🔴 **狀態判定在鎖之後**（理由同 `reopen`，兩者是同一個形狀）。
        #
        # 排在鎖外的話：`keep_edits` 在鎖外讀到「視同關閉」→ 並行的 `reopen` 取鎖、把課程
        # 轉成運作中的 `PUBLISHED` 並清空暫存 → `keep_edits` 取到鎖、`ensure_seeded` 種出
        # **一棵新的樹**並插上 `__kept`。
        #
        # 後果不是壞資料，而是**保證失效**：那門課從此恆有保留旗標，`discard_unkept` 永遠
        # 是 no-op，「沒按更新就離開 ＝ 放棄本次編輯」對它再也不成立——而那正是 #720 的
        # 主旨。設計上的不變量是「運作中的已發布課程恆無 `__kept`」，這一行是它的守門。
        if not is_effectively_closed(status=course.status, open_end_at=course.open_end_at, now=utcnow()):
            # ⛔ 不共用 `ET_COURSE_010`：那句話是「草稿請直接編輯後發布」，而這裡要說的是
            # 「這門課還在運作中，編輯請按『更新』」——下一步不同，比照 `006` / `007` 的理由。
            raise AppError(
                status_code=409,
                detail="僅已關閉課程可保留編輯，運作中的課程請改用「更新」",
                error_code="ET_COURSE_011",
            )
        writer = EtCourseStageWriter(self._stage)
        await writer.ensure_seeded(db, course_id, operator)
        node = await writer.course_node(db, course_id)
        if node is None:  # pragma: no cover - `ensure_seeded` 必定建出課程節點
            raise ValueError("暫存樹缺少課程節點（COURSE）")
        await writer.set_payload_flag(db, node.stage_id, KEPT_PAYLOAD_KEY, True, operator)
        await self._log(db, operator.user_id, course_id, "保留課程內容編輯（未對學員生效）")

    async def discard_unkept(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """進入編輯頁時丟棄**沒被明確保留**的暫存殘留（#720，2026-10-19 裁示 Q1 選項 1）。

        ## 為什麼進頁要丟

        「沒按更新就離開 ＝ 放棄本次全部編輯」若只靠前端的離開攔截，那個保證是**假的**
        ——關分頁、當機、斷線都繞得過去。留下的殘留最糟的地方不是它存在，而是教師
        **看不出那是殘留**：畫面長得跟自己上次存的一樣，他會以為那就是目前的內容。

        ## 與「取消」的差別

        `discard_content` 無條件清空（教師明確要丟）；本支只清**沒有 `KEPT_PAYLOAD_KEY`**
        的，已關閉課程按過「保留編輯」的那一份留著。

        ⚠️ 判準是旗標、**不是**「暫存樹的內容有沒有變過」：後者分不出「教師存心留下的」
        與「當機留下的」，而那正是本支要分的事。

        ## 草稿靜默略過

        草稿沒有暫存表，前端對所有狀態一律呼叫本支（擁有者進頁就打一次；#768 起非擁有者不打），所以這裡**不回 409**
        ——與 `discard_content` 不同：那支是教師按了鈕，誤導到草稿要看得見；這支是前端的
        例行動作，為它回錯誤只會逼前端去判斷狀態，而那個判斷遲早與後端分岔。

        📌 已知且接受：兩個分頁同時開著同一門已發布課程時，**後開的那個會靜默吃掉先開
        的編輯**。裁示時已攤開過（選項 1 的代價），反方向的代價是「保證是假的」。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status == COURSE_DRAFT:
            return
        await self._stage.lock_course(db, course_id)
        node = await EtCourseStageWriter(self._stage).course_node(db, course_id)
        if node is not None and node.payload.get(KEPT_PAYLOAD_KEY):
            return
        removed = await self._stage.discard(db, course_id)
        if removed:
            await self._log(db, operator.user_id, course_id, f"丟棄未保留的課程內容編輯殘留（{removed} 項）")

    async def discard_survey_edits(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """只放棄**問卷**的編輯，其餘內容的編輯保留（#712，2026-10-19 使用者裁示 B）。

        ## 這支端點存在的唯一理由：凍結後的出口

        問卷一旦有填答就不可改題（`ET_SURVEY_003`）。而 `update_question` 的選項是**全量
        覆寫**，`_ensure_survey_not_frozen` 的比對又把 `SOURCE_ID` 算進去，於是：

        | 時點 | 事件 |
        |---|---|
        | T1 | 教師改了既有題目（當時無填答，合法），暫存的選項全部換成新節點 |
        | T2 | 學員送出填答 |
        | T3 | 按「更新」→ 422。**把題幹一字不差改回去也沒用**——選項的識別碼回不來 |

        卡住的不只是問卷：該檢核跑在 `apply_stage` 最前面，所以章節、教材、測驗的編輯
        一起出不去。在本端點之前，唯一出路是 `discard_content`（丟掉**整門課**的編輯）。

        ## 做法是「重抄」不是「刪除」

        委派 `stage_repository.reseed_survey`：丟掉暫存的問卷子樹，再從活表原樣抄一份回來
        ——包含 `SOURCE_ID`，所以結構重新等於活表、更新過得去。
        ⛔ 只刪不抄會讓 `_delete_removed` 把活表的問卷判成「教師刪了它」而軟刪掉。

        ## 暫存區是空的時候什麼都不做

        沒有編輯工作階段就沒有「問卷的編輯」可放棄。此時若逕行重抄，會造出一棵**只有
        問卷**的暫存樹，而那在套用時等於「教師刪光了章節」——回 204 直接結束才是對的。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；409 `ET_COURSE_010` 草稿。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if course.status == COURSE_DRAFT:
            raise AppError(
                status_code=409,
                detail="草稿課程的編輯直接生效，沒有可放棄的暫存內容",
                error_code="ET_COURSE_010",
            )
        await self._stage.lock_course(db, course_id)
        if not await self._stage.has_stage(db, course_id):
            return
        await self._stage.reseed_survey(db, course_id, operator)
        # 只記動作、不記內容：暫存列從未對學員生效，寫進稽核沒有價值（同 `discard_content`）。
        await self._log(db, operator.user_id, course_id, "放棄尚未更新的課後問卷編輯")

    async def close(
        self, db: AsyncSession, course_id: int, req: CloseCourseReq, *, operator: OperatorInfo
    ) -> CourseStatusResult:
        """關閉課程（US11 AC 1 / FR-ET-US11-02）——立即轉 `CLOSED`，無過渡狀態。

        關閉**不做任何內容檢核**：它是收斂動作，把一門已發布的課程停下來不需要它合格。
        （再開課才要重跑檢核，見 `reopen`。）

        關閉當下作答中的 attempt **不受影響**——Attempt Snapshot 讓它可以完成並計分
        （FR-ET-US11-04，#279 已實作），本端點不去中止任何 attempt。

        Raises:
            AppError: 404 `ET_COURSE_001` 查無課程；403 `ET_COURSE_002` 非擁有者；
                409 `ET_COURSE_006` 課程狀態不允許關閉；409 `ET_LOCK_001` 版本不符。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        ensure_closable(course.status)

        closed_at = utcnow()
        # 兩個時間先取下來——`mark_closed` 是 ORM-enabled UPDATE，執行後 `course` 上的
        # 欄位會被 SQLAlchemy 同步，屆時再讀就分不出「更新前的值」與「剛寫進去的值」。
        # 關閉不動起訖時間，故此處讀到的即是回應要帶的值。
        open_start_at, open_end_at = course.open_start_at, course.open_end_at
        new_version = await self._courses.mark_closed(
            db, course_id, req.version, closed_at=closed_at, operator=operator
        )
        # `mark_closed` 以 `RETURNING` 回新版本，`None` 表示沒有列符合（版本不符）。
        ensure_version_matched(rowcount=0 if new_version is None else 1, entity="ET_COURSE")
        await self._log(db, operator.user_id, course_id, "關閉課程")

        return CourseStatusResult(
            course_id=course_id,
            status=COURSE_CLOSED,
            open_start_at=open_start_at,
            open_end_at=open_end_at,
            closed_at=closed_at,
            version=new_version,
        )

    async def reopen(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> CourseStatusResult:
        """「更新並重開課」（US11 AC 8 / FR-ET-US11-09）——套用暫存的編輯後回 `PUBLISHED`。

        ## 🔴 #720 把它從「狀態轉換」改成「更新 + 狀態轉換」

        關閉期間的編輯自 #631 起寫**暫存區**，而本方法原本**不套用暫存**、檢核也讀**活表**。
        兩件事合起來留下一個洞：教師在關閉期間把受訓對象清光（進暫存）、按再開課，檢核
        看活表還有配對就放行——課程回到 `PUBLISHED` 而它已經不符合發布條件，正是下面
        那段「不重跑等於把發布檢核變成一次性的」要防的事，只是繞道從暫存區進來。
        由 `test_關閉期間清空受訓對象後再開課被擋` 當場抓出來。

        ⇒ 順序固定為**檢核（讀暫存）→ 套用暫存 → 轉 `PUBLISHED` → 帶入寄信**，同一個交易。
        檢核未通過時活表一行都不會動（與 `update_published` 同一條理由）。

        ## 🔴 起訖時間取自暫存，請求**沒有 body**

        起訖時間自 #720 起是基本資料的一部分、進暫存區，所以：

        - `ensure_reopen_schedule` 檢核的是**真正會生效的那一組**。檢核 `req` 的值卻套用
          暫存的值，就是「檢核通過但生效後不合格」——#720 存在的意義就是消滅那件事
        - 併發改由**課程行鎖**序列化，比照 `content/apply`。教師手上的樂觀鎖令牌自 #720
          起是**暫存節點**的 `VERSION`，拿它去對活表的 `ET_COURSE.VERSION` 必然不符

        ⚠️ 沒有暫存區時走活表：此時起訖仍是關閉前那組（已過期），`ensure_reopen_schedule`
        會以 `ET_COURSE_008` 要教師先重設——那正是 FR-ET-US11-09「強制重新設定一組新的
        起訖時間」要的行為，只是改在基本資料卡填、不再有專屬的再開課表單。

        ## 為何重跑發布六項檢核（#288 SA Q2 裁示 A）

        2026-07-02 的變更明訂**關閉期間教師端課程內容仍可編輯**（供準備下次開課）。兩條
        規則放在一起就產生 spec 沒有回答的情形：教師可以在關閉期間把某章節刪光、把測驗
        配分改成不等於 100、或讓引用的 DM 文件被廢止，然後再開課——課程回到 `PUBLISHED`
        而它已經不符合發布條件。學員面對的會是 0 題的測驗（那是章節解鎖條件之一，他會
        卡在空考卷前）、配分不對的測驗、或指向廢止文件的教材。

        不重跑等於把發布檢核變成**一次性的**：課程只要關閉過一次，就能永久繞過它。

        故複用 `publish` 的同一組檢核與**同一個錯誤碼** `ET_PUBLISH_001` + `blockers`
        ——同一種語意不分兩碼，前端也能直接複用缺漏清單的呈現。

        > 也因此本方法放在 `publish_service` 而非 `service`：它需要 `_evaluate`
        > （快照 + 問 DM 廢止狀態）。三支狀態轉換（`publish` / `close` / `reopen`）
        > 放在同一支 service，是狀態機的三條邊。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；409 `ET_COURSE_007`
                課程狀態不允許再開課；422 `ET_COURSE_008` 新訖止時間未晚於當下；
                422 `ET_PUBLISH_001` 六項檢核未通過（body 另帶 `blockers`）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        # 先取行鎖再讀暫存樹——同 `update_published`：這整段（讀 → 檢核 → 套用 → 轉狀態）
        # 必須對同一門課序列化，否則教師雙擊會套用兩次。
        await self._stage.lock_course(db, course_id)
        await db.refresh(course)
        # 🔴 **狀態判定必須在鎖**之後**。**
        #
        # 原本它排在 `lock_course` 之前，而 #720 拿掉 request body 時連樂觀鎖一起拿掉了
        # ——`mark_reopened` 的 `WHERE version = ?` 現在吃的是持鎖後重讀的值、恆真，
        # 已不是第二道併發檢查。兩者相加的結果是：
        #
        #   兩個請求同時抵達 → 都在鎖外看到 `CLOSED` 而通過 → 甲取鎖、轉成 `PUBLISHED`
        #   → 乙取鎖，`refresh` 看到 `PUBLISHED` **但沒有人再問一次** → 照樣重開一次
        #
        # 可觀察的後果：`URGENT_REMIND_SENT` 被再次歸零，於是 SCHET002 對**已經寄過**
        # 加急提醒的課程全班重寄一次；稽核多一筆「更新並重開課」。
        #
        # ⚠️ 這是**退步**而非既有缺陷：#720 之前那第二個請求會吃 409 `ET_LOCK_001`。
        # 把檢查搬進鎖內，等於用行鎖取代原本樂觀鎖承擔的那件事。
        ensure_reopenable(status=course.status, open_end_at=course.open_end_at, now=utcnow())
        nodes = await self._stage.load_tree(db, course_id)

        if nodes:
            # ⚠️ `status` 傳 `COURSE_PUBLISHED`——快照描述的是「套用之後會是什麼樣子」，
            # 而那一刻課程就是已發布。`evaluate_publish` 目前不讀這個欄位，傳對的值是
            # 為了日後它開始讀的時候不會拿到 `CLOSED`。
            snapshot = to_course_snapshot(nodes, status=COURSE_PUBLISHED)
            start_at, end_at = snapshot.open_start_at, snapshot.open_end_at
            blockers = evaluate_publish(snapshot, obsolete_doc_ids=await self._obsolete_doc_ids(db, snapshot.doc_ids))
        elif await self._stage.has_stage(db, course_id):
            # 🔴 暫存列在、但全被教師刪光（判準同 `update_published` 與 `_evaluate_for_check`）。
            # 原本落到下面讀活表，於是活表完整就放行、而教師的刪除永遠不生效——預檢卻回
            # 「沒有章節」，兩邊對同一門課講相反的話（#767 code review MEDIUM）。
            # 樹是空的、讀不到起訖，沿用活表那組；缺漏清單會先以「沒有章節」擋下。
            start_at, end_at = course.open_start_at, course.open_end_at
            blockers = evaluate_publish(
                to_course_snapshot(nodes, status=COURSE_PUBLISHED), obsolete_doc_ids=frozenset()
            )
        else:
            # 沒開過編輯工作階段：起訖仍是關閉前那組，下面的 `ensure_reopen_schedule`
            # 會要教師先去基本資料卡重設。
            start_at, end_at = course.open_start_at, course.open_end_at
            blockers = await self._evaluate(db, course)

        ensure_reopen_schedule(open_end_at=end_at, now=utcnow())
        if blockers:
            raise AppError(
                status_code=422,
                detail="發布條件未滿足",
                error_code="ET_PUBLISH_001",
                extra={
                    "blockers": [{"code": b.code, "message": b.message, "target_id": b.target_id} for b in blockers]
                },
            )

        # 🔴 **套用在轉狀態之前**：轉成 `PUBLISHED` 的那一刻學員就看得到，而此刻活表裡
        # 必須已經是教師編好的內容。反過來做會有一小段視窗讓學員看到舊內容。
        if nodes:
            await apply_stage(db, course=course, nodes=nodes, operator=operator)
            await self._stage.clear(db, course_id, operator, stage_ids=[n.stage_id for n in nodes])

        # 同 `close`：先取下 `CLOSED_AT`，UPDATE 之後 `course` 上的值已被同步。
        closed_at = course.closed_at
        # ⚠️ 樂觀鎖令牌取**持鎖下重讀的活表版本**，不是教師手上那個——他手上的是暫存
        # 節點的版本（#720）。併發由上面的行鎖擋，這裡的 `version` 只是沿用 repository
        # 既有的 `WHERE` 形狀，不是第二道併發檢查。
        new_version = await self._courses.mark_reopened(
            db,
            course_id,
            course.version,
            open_start_at=start_at,
            open_end_at=end_at,
            operator=operator,
        )
        ensure_version_matched(rowcount=0 if new_version is None else 1, entity="ET_COURSE")
        await self._log(db, operator.user_id, course_id, "更新並重開課")

        # **比照發布，依目前全部受訓對象帶入新符合者並寄邀請信**（#678，2026-10-16 裁示）。
        # 原設計「再開課不是一次新的招生、刻意不帶入」的前提是關閉期間不能改受訓對象；
        # #586 起可以了，而關閉期間不帶入（FR-ET-US11-07）、貼標追溯也排除已關閉課程，
        # 不在此帶入的話，關閉期間新增的配對與新貼標的人**永遠不會被帶入**。
        #
        # **不重產邀請碼**（Clarifications 仍成立）——邀請碼恢復有效是各處守門判 `STATUS`
        # 自動達成的。
        invited = await self.enroll_audiences(db, course, operator=operator)
        return CourseStatusResult(
            course_id=course_id,
            status=COURSE_PUBLISHED,
            open_start_at=start_at,
            open_end_at=end_at,
            # 保留最近一次關閉時間供追溯（FR-ET-US11-10）——故前端不可用「有沒有值」
            # 判斷是否已關閉，那要看 `status`。
            closed_at=closed_at,
            version=new_version,
            # #720：供結果視窗顯示（比照發布）。**據實顯示 0**——0 代表課程掛的受訓對象
            # 沒有任何人符合，那是教師需要知道的事實，不是可以隱藏的空狀態。
            invited_count=len(invited),
            # 沿用原碼、不重產。教師可能從未抄下來過（#247），重開課是再給他一次機會。
            invitation_code=course.invitation_code,
        )

    async def enroll_audiences(self, db: AsyncSession, course, *, operator: OperatorInfo) -> list[str]:
        """依課程**目前全部**受訓對象配對帶入學員，並只寄信給本次真的被加入者。

        發布（FR-ET-US3-12）、再開課（FR-ET-US11-09，#678）、延長期間使視同關閉的課程
        復活（#678）三處共用——三者都是「課程從學員不可見回到可見」的那一刻，之前不帶入的
        配對與貼標都要在此補上。

        - 已在課程中者略過、**已被移除者不會被帶回**：`bulk_enroll_returning` 為
          `ON CONFLICT DO NOTHING` 且只回傳真正新增者（⛔ 勿改成 DO UPDATE，見其 docstring）
        - 寄信前 `refresh` 課程是**防禦性**的：信裡有起訖時間與邀請碼，而呼叫端剛改過它們。
          現行 `mark_published` / `mark_reopened` / `update_basic` 皆為 ORM-enabled UPDATE，
          SQLAlchemy 已同步 identity map（`synchronize_session="auto"`），信件用到的欄位
          （名稱、起訖、邀請碼）**本來就是新值**（見 `mark_published` docstring）——故拿掉
          這行**沒有任何測試會紅**（#678 變異檢查實測）。⚠️ 以 SQL 函式寫入的欄位（如
          `FIRST_PUBLISHED_AT` 的 `COALESCE`）是被標為過期而非就地更新。保留 refresh 是為了
          不讓「信的內容正確」相依於三支 repository 方法都維持同一種 UPDATE 寫法
        - 寄信失敗不回滾加入（AC 3）——由 `EtNotifier` 吞掉 `AppError`，此處不需 try/except

        Returns:
            本次新加入者的 `USER_ID`。
        """
        course_id = course.course_id
        invited_ids = await self._tag_invite.bulk_enroll_returning(
            db, course_id, await self._tag_invite.target_user_ids(db, course_id), operator=operator
        )
        if not invited_ids:
            return []
        await self._log(db, operator.user_id, course_id, f"依受訓對象帶入 {len(invited_ids)} 位學員")
        await db.refresh(course)
        await self._invite_mailer.send_course_invite(
            db, course=course, invitation_code=course.invitation_code, user_ids=invited_ids
        )
        return invited_ids

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def backfill_new_tag_members(
        self, db: AsyncSession, course, pairs: set[Pair], *, operator: OperatorInfo
    ) -> None:
        """新增配對 → 補帶入該配對人員並寄通知信（FR-ET-US8-04 / #273 / #538）。

        ⚠️ **呼叫點於 #720 從 `update_basic` 移到 `update_published`**（套用暫存之後）。
        原本教師按「儲存」當下就寄，而暫存模式下那封信寫的是**還沒發生的事**：信裡說
        「你被加入了某課程」，但那組配對還在暫存區，他點進去什麼都看不到；若教師接著按
        「取消」，那組配對從頭到尾不曾存在，而信已經寄出去了。

        **只對新增的配對解析人員**（`target_user_ids_for_pairs`）：用全部課程配對會把
        「發布後才被貼上舊配對的人」也一併帶入，而那條路徑另有出口（貼標追溯於貼標
        當下觸發），在這裡順手做會讓同一人被兩條路徑各邀請一次。

        草稿課程不走這裡——草稿的配對可自由增刪，帶入與寄信一律等到發布當下
        （FR-ET-US3-12）；否則教師編輯期間每加一組配對就會寄出一批信。

        既有學員不重複加入由 `bulk_enroll_returning` 的 `ON CONFLICT DO NOTHING` 保證，
        且它只回傳真正新增者，故寄信對象自然也不含既有學員。
        """
        user_ids = await self._tag_invite.target_user_ids_for_pairs(db, course.course_id, list(pairs))
        invited = await self._tag_invite.bulk_enroll_returning(db, course.course_id, user_ids, operator=operator)
        if not invited:
            return
        await self._log(db, operator.user_id, course.course_id, f"新增受訓對象補帶入 {len(invited)} 位學員")
        # 重新載入課程（防禦性）：信裡有課程名稱與起訖，`apply_stage` 剛把它們寫回活表。
        # 那是 ORM-enabled UPDATE、已同步 identity map，現況下手上的物件本來就是新值——
        # 保留 refresh 是不讓信的內容相依於該寫法（#678 查證）。
        await db.refresh(course)
        await self._invite_mailer.send_course_invite(
            db, course=course, invitation_code=course.invitation_code, user_ids=invited
        )

    async def ensure_revival_publishable(
        self, db: AsyncSession, course, *, new_end_at: datetime | None, now: datetime
    ) -> bool:
        """`PUT /courses/{id}` 延長期間若會讓一門**視同關閉**的課程復活，重跑發布六項檢核（#301）。

        ## 為何 `PUT` 也要檢核

        #288 讓「再開課」重跑檢核（SA Q2 裁示 A），理由是「不重跑等於把發布檢核變成一次性的」。
        但**期間已過**的課程不必走再開課就能復活——狀態仍是 `PUBLISHED`（到期自動轉 `CLOSED`
        由 SCHET002 每日 08:00 執行，每門課到期後都必經這個窗口；見 `rules.is_effectively_closed`），
        教師只要把 `OPEN_END_AT` 改到未來或清空即可。

        六項之一是 `OBSOLETE_DOC`（教材不得引用已廢止的 DM 文件）。該路徑會讓學員繼續讀一份
        已廢止的 SOP 當現行教材，而那正是該項檢核存在的理由；另有 `NO_CHAPTER`（章節被刪光）
        與 `QUIZ_NO_QUESTION`（0 題測驗會讓學員卡在空考卷前）。

        ## 為何只在「復活」時觸發

        若每次 `PUT` 都檢核，教師想把一門正常運作的課程延長一個月，會被「課程至少須有 1 個
        章節」之類與其操作無關的訊息擋下。故條件收窄為三者同時成立：

        1. 狀態為 `PUBLISHED`——草稿本來不對學員可見（發布時才檢核）；`CLOSED` 改不了狀態、
           只能走 `reopen`（那條已經會檢核）
        2. 變更前**視同關閉**（`is_effectively_closed`）
        3. 變更後不再視同關閉——新訖止晚於當下，或**清空**（`None` 語意為「沒有結束日」）

        與 `reopen` 共用同一組檢核與同一個錯誤碼 `ET_PUBLISH_001` + `blockers`，前端可直接
        複用缺漏清單的呈現。

        Returns:
            本次變更是否讓課程**復活**——呼叫端據以比照再開課執行 `enroll_audiences`（#678）。

        Raises:
            AppError: 422 `ET_PUBLISH_001` 六項檢核未通過（body 另帶 `blockers`）。
        """
        if course.status != COURSE_PUBLISHED:
            return False
        was_closed = is_effectively_closed(status=course.status, open_end_at=course.open_end_at, now=now)
        will_be_open = new_end_at is None or new_end_at > now
        if not (was_closed and will_be_open):
            return False

        blockers = await self._evaluate(db, course)
        if blockers:
            raise AppError(
                status_code=422,
                detail="發布條件未滿足",
                error_code="ET_PUBLISH_001",
                extra={
                    "blockers": [{"code": b.code, "message": b.message, "target_id": b.target_id} for b in blockers]
                },
            )
        return True

    async def _evaluate_for_check(self, db: AsyncSession, course) -> tuple[PublishBlocker, ...]:
        """預檢要評估的是**按下去之後會生效的那一份**（#767 ⑧）。

        草稿直寫活表，評估活表即可。已發布 / 已關閉課程的編輯在暫存區：有暫存時必須
        評估暫存樹，與「更新」「更新並重開課」相同——否則預檢永遠回「沒有缺漏」，教師要
        到真正送出才被擋，而那時確認視窗已經問過一次了。

        判準用 `has_stage` 而非 `nodes` 是否為空，理由同 `apply_content`：教師把內容
        全刪光時暫存列仍在、只是全被軟刪，那時要回「沒有章節」而不是活表的結果。

        ⚠️ 不取行鎖：預檢唯讀，送出時「更新」會在鎖內再評估一次，那一次才算數。

        Args:
            course: 已通過擁有者檢查的課程列。

        Returns:
            缺漏清單；空 tuple 代表可通過。
        """
        if course.status != COURSE_DRAFT:
            nodes = await self._stage.load_tree(db, course.course_id)
            if nodes or await self._stage.has_stage(db, course.course_id):
                snapshot = to_course_snapshot(nodes, status=course.status)
                return evaluate_publish(snapshot, obsolete_doc_ids=await self._obsolete_doc_ids(db, snapshot.doc_ids))
        return await self._evaluate(db, course)

    async def _evaluate(self, db: AsyncSession, course) -> tuple[PublishBlocker, ...]:
        """組快照 → 問 DM 廢止狀態 → 交給純函式判斷。"""
        snapshot = await self._publish.snapshot(db, course)
        return evaluate_publish(snapshot, obsolete_doc_ids=await self._obsolete_doc_ids(db, snapshot.doc_ids))

    async def _obsolete_doc_ids(self, db: AsyncSession, doc_ids: frozenset[str]) -> frozenset[str]:
        """向 DM 逐一問廢止狀態（經 `app/services` 唯一跨模組出口）。

        **取不到的文件不列入廢止**（DM 端以 `AppError` 表達查無 / 無發布版）：DM 沒有
        刪除文件的操作，已發布文件只有「編輯上傳新版本」與「廢止」兩種動作，且教師
        能選到的必然是已發布文件——因此「取不到」是正常操作到不了的狀態
        （#204 SA Q2 撤回時已核對）。這裡不讓例外冒上去只是防禦：一份查詢失敗的引用
        不該讓整個發布流程炸掉。
        """
        if not doc_ids:
            return frozenset()
        client = get_dm_document_client()
        obsolete: set[str] = set()
        for doc_id in sorted(doc_ids):
            try:
                current = await client.get_current_by_doc_id(db, doc_id)
            except AppError:
                continue
            if current.obsolete:
                obsolete.add(doc_id)
        return frozenset(obsolete)

    async def _generate_code(self, db: AsyncSession) -> str:
        """產生全域唯一之邀請碼。

        `exists` 須為**同步** callable（`generate_invitation_code` 之約束），故先把
        既有邀請碼一次撈成集合再包成 lambda——在其中等待非同步 I/O 會與既有事件迴圈
        衝突。

        長度取自 `DP_PARAM.ET_INVITATION_CODE_LENGTH`；> 8 時 `generate_invitation_code`
        **fail-fast 不得靜默截斷**（欄位為 `VARCHAR(8)`，截斷會破壞唯一性假設並產生
        難以追查的碰撞）。
        """
        length = await self._params.get_int_param(db, _CODE_LENGTH_PARAM, "VALUE", _DEFAULT_CODE_LENGTH)
        used = await self._courses.list_invitation_codes(db)
        return generate_invitation_code(length=length, exists=lambda code: code in used)

    async def _require_owned(self, db: AsyncSession, course_id: int, actor_id: str):
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def _log(self, db: AsyncSession, operator_id: str, course_id: int, description: str) -> None:
        """發布 / 關閉 / 再開課之稽核（US11 在 `spec.md` §稽核來源功能碼清單內）。

        帶 `source_ip`：關閉一門課會立刻影響**全部在籍學員**，這筆紀錄少了來源 IP 就
        只能追到帳號、追不到來源。`invitation` 與 `enrollment` 的稽核本來就都帶，
        course 模組原先漏了。
        """
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
            source_ip=get_client_ip(),
            # 供 DP05 對象欄顯示課程名而非 ID（#717）；取當下值，課程改名不改寫歷史。
            after_value=await course_audit_payload(db, course_id) or None,
        )
