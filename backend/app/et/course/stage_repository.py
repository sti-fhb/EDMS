"""已發布課程編輯暫存區的存取（#631）。

職責只有三件：**從活表種出整棵暫存樹**、**把暫存樹讀回來**、**清空**。
套用（暫存 → 活表）在 `stage_apply.py`；業務規則在 `stage_rules.py`（純函式）。

## 為何 seed 是「整棵複製」而不是「用到才複製」

暫存區存的是**完整的目標內容樹**，所以編輯端讀取就是直接讀它，不必把差異疊加回活表。
疊加邏輯會散落在 12 個讀取端點，而漏掉一處的症狀是**教師看不到自己剛做的編輯**。

代價是第一次編輯時多一次整棵複製。課程內容樹的量級是「章節 × 項目 × 題目」，
實務上數十到數百列，一次性成本可忽略。

## 活表遍歷不在這裡

在 `stage_live_tree.load_live_tree`，**與套用端的刪除偵測共用**——兩邊對「哪些列算
課程內容」必須給出完全相同的答案，理由見該模組 docstring。
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.course.models import EtCourse, EtCourseContentStage
from app.et.course.stage_entities import SPEC_BY_TYPE, EntitySpec, dumps_payload, parse_payload, to_payload_dict
from app.et.course.stage_live_tree import LiveKey, load_live_tree
from app.et.course.stage_rules import (
    ENTITY_SURVEY,
    ENTITY_SURVEY_OPTION,
    ENTITY_SURVEY_QUESTION,
    StageNode,
)

logger = logging.getLogger(__name__)

#: 問卷子樹的三種實體型別——`reseed_survey` 的作用範圍。
#:
#: ⚠️ 日後若問卷底下多出第四種型別，**這裡不補就會變成「丟了一半」**：舊的那種被刪掉、
#: 新的那種留著，而留著的那批指向已不存在的父節點 ⇒ `_validate_tree` 在套用時 500。
#: 由 `test_問卷子樹型別清單與對照表一致` 比對 `SPEC_BY_TYPE`，不靠人記得。
_SURVEY_ENTITY_TYPES: Final = (ENTITY_SURVEY, ENTITY_SURVEY_QUESTION, ENTITY_SURVEY_OPTION)


@dataclass(frozen=True)
class _SeedCtx:
    """一次 seed 期間共用的不變值。

    ⛔ 不放在 repository 實例上——本專案的 repository 一律無狀態，帶了狀態的那一份
    在同一請求內被重用時會用到上一次的操作者與時間戳。
    """

    course_id: int
    operator: OperatorInfo
    now: datetime


def to_payload(spec: EntitySpec, row: object) -> str:
    """把活表列的內容欄位序列化成 `PAYLOAD`（seed 一棵樹時用）。

    🔴 編碼一律經 `dumps_payload`——它是序列化的**唯一一道門**，另兩道是
    `stage_writer.append` 與 `update_payload`。不可序列化的型別在那裡會 `TypeError`，
    **那是刻意不接住的**：內容表日後加了不可序列化的欄位，推導會自動把它納入 payload，
    當場爆出來才看得見；靜默塞個字串進去才是真正的問題（套用時寫回活表會變成錯的型別）。

    ⚠️ **`datetime` 已於 #720 成為例外**（課程的起訖時間）：寫出去是 ISO 8601、
    `parse_payload` 讀回來還原成 `datetime`。那是**成對的**轉換，不是「塞個字串」——
    承重點因此轉移到 `parse_payload`，由 `test_et_course_stage_payload_datetime.py` 守住。
    ⛔ 不要為了讓別的型別過而加 `default=str`：那會讓上一段講的靜默寫入字串重新變成可能。
    """
    return dumps_payload(spec.entity_type, to_payload_dict(spec, row))


class EtCourseStageRepository:
    """暫存區的讀寫。"""

    async def has_stage(self, db: AsyncSession, course_id: int) -> bool:
        """該課程是否有**編輯工作階段開著**（教師開始編輯了、還沒按「更新」或「取消」）。

        🔴 **刻意不帶 `DELETED = 0`。** 判準是「這門課在暫存表裡有沒有列」，不是「暫存樹
        空不空」——兩者在教師**把章節全刪光**時會分岔，而分岔的後果是靜默的：

        1. 暫存樹變空 ⇒ 編輯頁退回去讀活表 ⇒ **剛刪掉的章節全部復活在畫面上**
        2. `has_pending_changes` 變假 ⇒ 「更新」鈕暗掉，教師沒有任何方式讓刪除生效
        3. 他接著新增一章 ⇒ `ensure_seeded` 以為沒有暫存區 ⇒ **從活表重新 seed** ⇒
           剛才刪掉的全部回來，再加上新的那一章

        教師自己刪的列是軟刪（`delete_subtree`），列還在 ⇒ 本方法回真 ⇒ 不會重新 seed。
        工作階段結束時（`clear` 套用後／`discard` 放棄）列是**硬刪**、整個不見 ⇒ 回假。

        ⛔ 不要「順手」補回 `DELETED = 0`——那正是上面那個 bug
        （2026-10-16 code review MEDIUM）。`test_刪光章節後不得重新_seed` 會紅。
        """
        found = await db.scalar(
            select(EtCourseContentStage.stage_id).where(EtCourseContentStage.course_id == course_id).limit(1)
        )
        return found is not None

    async def load_tree(self, db: AsyncSession, course_id: int) -> tuple[StageNode, ...]:
        """讀回整棵暫存樹（扁平，彼此以 `parent_stage_id` 串接）。"""
        rows = await db.scalars(
            select(EtCourseContentStage)
            .where(EtCourseContentStage.course_id == course_id, EtCourseContentStage.deleted == 0)
            .order_by(EtCourseContentStage.stage_id)
        )

        def _payload(raw: str, entity_type: str) -> dict:
            """⚠️ `PAYLOAD` 不是 JSON object 時**明確報錯**。

            非 dict 的話，下游 `f in node.payload` 會退化成子字串 / 成員測試、
            `payload[f]` 拋 TypeError——兩種都是難讀的 500。目前只有伺服端寫入故不可達，
            但這張表是 PR 2 的編輯端要寫的，守門放在讀取這一側才涵蓋得到全部寫入者。

            ⚠️ 訊息是**固定文案**、細節只進 log——與 `stage_writer._view` 這支手足一致
            （2026-10-18 security review L-1：上一輪把 detail 收斂的修法漏了這一支，
            兩支不一致的話，下一個人會照錯的那支抄）。`AppError.detail` 會原樣成為回應的
            `error_message`，**含 500**。
            """
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                logger.error(
                    "ET 暫存列的 PAYLOAD 不是 JSON object：course_id=%s type=%s", course_id, type(parsed).__name__
                )
                raise AppError(
                    status_code=500,
                    detail="課程內容暫存資料異常，請重新載入後再試",
                    error_code="ET_STAGE_001",
                )
            # ⚠️ ISO 8601 還原成 `datetime`（#720）。少了它，`evaluate_publish` 會拿字串
            # 去跟 `datetime` 比較，而 `_upsert` 會把字串寫進 `TIMESTAMPTZ` 欄位。
            return parse_payload(entity_type, parsed)

        return tuple(
            StageNode(
                stage_id=r.stage_id,
                entity_type=r.entity_type,
                source_id=r.source_id,
                parent_stage_id=r.parent_stage_id,
                sort_order=r.sort_order,
                payload=_payload(r.payload, r.entity_type),
                version=r.version,
            )
            for r in rows.all()
        )

    async def lock_course(self, db: AsyncSession, course_id: int) -> None:
        """對課程列取**行鎖**，序列化同一門課的「更新」。

        🔴 沒有這把鎖，`load_tree → apply_stage → clear` 不是原子的。預設隔離等級是
        READ COMMITTED，兩個並發請求（教師雙擊、或兩個分頁同時按）會**各自讀到完整
        的暫存樹**，兩邊都跑新增 ⇒ `SOURCE_ID` 為 `None` 的節點被插入兩次，活表出現
        重複的章節 / 項目 / 題目。唯一索引擋不住——重複的那幾列排序各自獨立。

        ⚠️ 「第二次會看到空的暫存區而成為 no-op」只在兩次請求**先後**執行時成立。
        2026-10-14 的 code review 推翻了那個判斷。

        ⭐ 是悲觀鎖不是樂觀鎖：要序列化的是整段流程，不是偵測單一列的版本衝突。
        """
        # 🔴 **`FOR NO KEY UPDATE` 而非 `FOR UPDATE`**（2026-10-18 code review HIGH 2）。
        #
        # `FOR UPDATE` 與**外鍵檢查**取的 `FOR KEY SHARE` 互斥。而有 FK 指向 `ET_COURSE`
        # 的表包括 `ET_ENROLLMENT` / `ET_PROGRESS` / `ET_QUIZ_ATTEMPT_M` /
        # `ET_QUIZ_RETRY_RESET`——也就是**學員加入課程、寫學習進度、開始作答**那幾條路徑。
        #
        # 於是教師只要持有這把鎖，同課程的學員就會被擋住。上傳 500 MB 影片時那段可以長
        # 達數分鐘（見 `material/service.upload_video` 的取鎖位置），而學員端沒有任何
        # 訊息，只會卡住。
        #
        # `FOR NO KEY UPDATE` 不與 `FOR KEY SHARE` 衝突，但仍與自己互斥——編輯與「更新」
        # 照樣序列化。本流程不改 `ET_COURSE` 的主鍵，語意上足夠。
        #
        # ⛔ 不要「為了保險」改回 `FOR UPDATE`：那會讓學員端的寫入排在教師的編輯後面。
        await db.execute(
            select(EtCourse.course_id).where(EtCourse.course_id == course_id).with_for_update(key_share=True)
        )

    async def clear(
        self, db: AsyncSession, course_id: int, operator: OperatorInfo, *, stage_ids: Sequence[int]
    ) -> None:
        """套用成功後清掉暫存列——**只清指定的那批 `STAGE_ID`**。

        ⛔ **不可改回 `WHERE COURSE_ID = ?`**：那會連「`load_tree` 之後才寫進來的編輯」
        一起清掉，而那筆編輯從來沒有被套用過——教師的輸入靜默消失，沒有任何錯誤訊息。
        呼叫端一律傳入自己實際載入並套用的那批 id。

        🔴 **硬刪除——這是專案「禁止硬刪除」規則的例外**（2026-10-16 使用者裁示，
        見 `docs/ref/sti-backend-ref.md` 的例外表）。理由：

        1. **本表是暫時性工作區，不是業務紀錄。** 被清掉的列，其內容在同一個交易裡
           已經整批複製進活表；稽核軌跡落在活表與 `DP_AUDIT_LOG`，不在這裡。
        2. **軟刪會讓「有沒有編輯工作階段開著」失去判準。** 教師自己刪章節也是軟刪，
           兩種 `DELETED = 1` 分不出來——見 `has_stage` 的 docstring，那是個會讓刪除
           靜默復活的 bug。

        ⚠️ 連帶：`operator` 目前用不到（硬刪沒有 `UPDATED_USER` 可寫）。保留參數是為了
        呼叫端形狀不變，且日後若改回軟刪不必再改簽名。
        """
        if not stage_ids:
            return
        await db.execute(
            delete(EtCourseContentStage).where(
                EtCourseContentStage.course_id == course_id,
                or_(
                    EtCourseContentStage.stage_id.in_(list(stage_ids)),
                    # 🔴 **連教師在本次工作階段刪掉的（軟刪）那些一起清**。
                    #
                    # 本表的 `PARENT_STAGE_ID` 指向自己（`FK_..._PARENT`）。教師刪掉的節點
                    # 是軟刪，`load_tree` 濾掉它 ⇒ 它不在 `stage_ids` 裡，但它的父節點在
                    # ⇒ 刪父違反外鍵，整個「更新」500。**教師只要刪過任何東西再按更新就會
                    # 中**（2026-10-17 由 `test_刪除題目也能要求重測` 抓到）。
                    #
                    # 軟刪的列**不可能**被未來任何一次套用用到（`load_tree` 永遠看不到
                    # 它們），所以隨工作階段一起結束是正確的，不是順手清垃圾。
                    #
                    # ⛔ 仍然不可改成 `WHERE COURSE_ID = ?`：那會連「`load_tree` 之後才寫
                    # 進來、還沒被套用」的編輯（`DELETED = 0`）一起刪掉。兩個條件的分界正
                    # 好是 `DELETED`。
                    EtCourseContentStage.deleted == 1,
                ),
            )
        )
        await db.flush()

    async def discard(self, db: AsyncSession, course_id: int) -> int:
        """放棄整個編輯工作階段——硬刪該課程**全部**暫存列，回傳刪掉幾列。

        教師按「取消」時走這條：課程回到學員目前看到的版本（活表一行都不會動）。

        ⛔ 與 `clear` 不同，這裡**刻意**是 `WHERE COURSE_ID = ?` 而非指定 id：教師要放棄
        的是「我這次編輯的全部」，不是某一批。呼叫端須已持有 `lock_course`，否則同時
        按下的「更新」可能把部分內容套用出去。

        ⚠️ 硬刪的理由同 `clear`——這些列從未進過活表，放棄之後沒有任何保存價值，
        而留著會讓 `has_stage` 永遠回真、教師再也開不了新的編輯工作階段。
        """
        result = await db.execute(delete(EtCourseContentStage).where(EtCourseContentStage.course_id == course_id))
        await db.flush()
        return result.rowcount or 0

    async def reseed_survey(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> int:
        """把暫存區的**問卷子樹**丟掉、從活表重抄一份，回傳重抄了幾列（#712）。

        ## 為什麼需要「只放棄問卷」這個粒度

        `update_question` 的選項是**全量覆寫**（舊節點軟刪、新節點以 `SOURCE_ID = None`
        新增）。而 `stage_apply._ensure_survey_not_frozen` 的結構比對把 `SOURCE_ID` 算進去，
        所以**任何一次題目編輯都會讓暫存結構永遠不等於活表**——教師就算把題幹一字不差地
        改回去也一樣。

        於是只要編輯期間出現填答，整門課的「更新」就卡死（該檢核跑在 `apply_stage` 最前面，
        章節與測驗一起陪葬），而唯一出路是放棄**全部**編輯。本方法給出一條只丟問卷的路。

        ⛔ **不可以改成「只刪不抄」。** `_delete_removed` 以「活表有、暫存沒有」判定教師刪了
        它——問卷節點整個消失會讓它把**活表的問卷連同題目、選項一起軟刪**，而那會連帶
        既有填答的指向。重抄才是正確的「回到原狀」。

        ⚠️ 呼叫端須先確認**暫存區不是空的**。對空的暫存區重抄問卷會造出一棵只有問卷的
        殘樹，而那在套用時等於「教師刪光了章節」。

        ⚠️ 也須先持有 `lock_course`：同時按下的「更新」可能正在讀這批列。

        Returns:
            重抄進暫存的列數。活表沒有問卷時回 0（代表那份問卷是本次新建的，丟掉就沒了）。
        """
        await db.execute(
            delete(EtCourseContentStage).where(
                EtCourseContentStage.course_id == course_id,
                EtCourseContentStage.entity_type.in_(_SURVEY_ENTITY_TYPES),
            )
        )
        await db.flush()

        nodes = await load_live_tree(db, course_id)
        root = next((n for n in nodes if n.entity_type == ENTITY_SURVEY), None)
        if root is None:
            return 0

        # 問卷子樹只有三層（問卷 → 題目 → 選項），逐層往下收。
        subtree: dict[LiveKey, object] = {root.key: root}
        for _ in range(2):
            subtree.update({n.key: n for n in nodes if n.parent_key in subtree})

        ctx = _SeedCtx(course_id=course_id, operator=operator, now=utcnow())
        stage_id_by_key: dict[LiveKey, int] = {}
        # `load_live_tree` 保證父在子之前，子層查父層的 `STAGE_ID` 必定查得到。
        for node in (n for n in nodes if n.key in subtree):
            parent_stage_id = None if node.parent_key is None else stage_id_by_key[node.parent_key]
            stage_id_by_key[node.key] = await self._add(
                db, ctx, node.entity_type, node.row, parent=parent_stage_id, sort_order=node.sort_order
            )
        await db.flush()
        return len(stage_id_by_key)

    async def seed_from_live(self, db: AsyncSession, course_id: int, operator: OperatorInfo) -> None:
        """把活表的內容樹整棵複製進暫存區。

        遍歷用 `stage_live_tree.load_live_tree`——**與套用端的刪除偵測共用同一支**。
        各寫一份的話，只有 seed 漏搬某一種時，刪除偵測會把它判成「教師刪了它」而在按下
        「更新」時連帶軟刪（見該模組 docstring）。

        ⚠️ 呼叫端須先確認暫存區是空的——重複 seed 會被唯一索引
        `(COURSE_ID, ENTITY_TYPE, SOURCE_ID)` 擋下。那是正確的 fail-closed，但訊息不好讀。
        """
        ctx = _SeedCtx(course_id=course_id, operator=operator, now=utcnow())
        stage_id_by_key: dict[LiveKey, int] = {}

        # `load_live_tree` 保證父節點排在子節點之前，所以查父層的 `STAGE_ID` 必定查得到。
        for node in await load_live_tree(db, course_id):
            parent_stage_id = None if node.parent_key is None else stage_id_by_key[node.parent_key]
            stage_id_by_key[node.key] = await self._add(
                db, ctx, node.entity_type, node.row, parent=parent_stage_id, sort_order=node.sort_order
            )
        await db.flush()

    async def _add(
        self, db: AsyncSession, ctx: _SeedCtx, entity_type: str, row: object, *, parent: int | None, sort_order: int
    ) -> int:
        """新增一列暫存並回傳其 `STAGE_ID`（供子層當 `PARENT_STAGE_ID`）。"""
        spec = SPEC_BY_TYPE[entity_type]
        stage = EtCourseContentStage(
            course_id=ctx.course_id,
            entity_type=entity_type,
            source_id=getattr(row, spec.pk),
            parent_stage_id=parent,
            sort_order=sort_order,
            payload=to_payload(spec, row),
            # 🔴 **樂觀鎖的初值承接活表那一列**（#631 PR 2）。
            #
            # 教師開編輯頁時，第一次編輯之前還沒有暫存列，前端拿到的 `VERSION` 來自活表。
            # 初值若設 0，那第一次編輯必然 409（`WHERE version = 3` 對上 `version = 0`）
            # ——教師會看到「資料已被其他使用者修改」，而根本沒有別人。
            #
            # ⚠️ 承接的只是**初值**：此後暫存列自己遞增，活表那一列不動，兩者就分岔了。
            # 下一次 seed（清空後再編輯）會再承接一次當時的活表值。
            version=getattr(row, "version", 0),
            created_user=ctx.operator.user_id,
            created_date=ctx.now,
        )
        db.add(stage)
        # 🔴 **必須當場 flush**：子層要拿它的 `STAGE_ID` 當父參照，而那是 Identity 欄位，
        # 不 flush 取不到。
        await db.flush()
        return stage.stage_id


def nodes_by_type(nodes: Sequence[StageNode], entity_type: str) -> list[StageNode]:
    """測試與套用端共用的小工具。"""
    return [n for n in nodes if n.entity_type == entity_type]
