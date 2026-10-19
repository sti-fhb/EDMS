"""ET05 課程骨架與章節編排 Service（US3 / #202）；亦含 ET01 課程清單（US7 / #299）。

**稽核**：ET 於 `spec.md` §稽核來源功能碼明列 `ET-COURSE` 涵蓋「課程建立 / 編輯 /
發布 / 關閉 / 再開課，及其下章節、教材、測驗、問卷之編修與刪除」，故本模組之 CUD
一律寫 `DP_AUDIT_LOG`——此為 ET spec 對 `sti-backend-modules`「新模組預設不寫
audit log」之明文加嚴，非疏漏。

**授權分兩層**：
1. 建立課程須具「教師」角色（SA 裁示 Q2，#202）
2. 編輯 / 刪除 / 章節操作須為**擁有者**（`spec.md` §擁有權判定）

讀取端不套第 2 層——他人課程可閱覽，由回應之 `is_owner` 讓前端呈現唯讀。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.pagination import PaginatedResult, paginate
from app.core.utils import utcnow
from app.dp.users.account_status import is_account_disabled
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.audit_target import course_audit_payload
from app.et.catalog.models import TAG_TYPE_AUDIENCE, TAG_TYPE_UNIT
from app.et.catalog.pair import Pair
from app.et.common.optimistic_lock import ensure_version_matched
from app.et.constants import ITEM_MATERIAL
from app.et.course.publish_service import EtPublishService
from app.et.course.repository import (
    EtChapterRepository,
    EtCourseRepository,
    EtCourseTagRepository,
    EtItemRepository,
)
from app.et.course.rules import (
    ensure_deletable,
    ensure_item_reorder_complete,
    ensure_owner,
    ensure_reorder_complete,
    ensure_schedule_not_cleared,
    ensure_tag_change_allowed,
    is_effectively_closed,
    resequence,
)
from app.et.course.schemas import (
    AudiencePair,
    Capabilities,
    ChapterCreateReq,
    ChapterItem,
    ChapterRenameReq,
    ChapterReorderReq,
    CourseCard,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseRow,
    CourseUpdateReq,
    ItemCreateReq,
    ItemReorderReq,
    ItemRow,
    OwnerOption,
    TagOption,
)
from app.et.course.stage_repository import EtCourseStageRepository
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE_TAG,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_QUESTION,
    ENTITY_QUIZ,
)
from app.et.course.stage_writer import EtCourseStageWriter, exposed_id, is_staged
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.enrollment.tag_invite import EtTagInviteRepository
from app.et.material.repository import EtMaterialRepository
from app.et.notify.course_update import CourseUpdateMailer
from app.et.notify.mailer import CourseInviteMailer
from app.et.quiz.repository import DEFAULT_MAX_RETRY, DEFAULT_PASS_SCORE, EtQuizRepository
from app.et.roles.authz import ET_ADMIN, ET_STUDENT, ET_TEACHER
from app.services import AuditLogService

_MODULE = "ET"
_FUNC_NAME = "ET-COURSE"

_NOT_FOUND = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
#: `ensure_version_matched` 的實體標籤（僅供日誌辨識，不進錯誤訊息）。
_STAGE_ENTITY = "ET_COURSE_CONTENT_STAGE"

_CHAPTER_NOT_FOUND = AppError(status_code=404, detail="查無此章節", error_code="ET_CHAPTER_001")
_ITEM_NOT_FOUND = AppError(status_code=404, detail="查無此章節項目", error_code="ET_ITEM_001")


@dataclass(frozen=True)
class _StagedBasic:
    """暫存區裡的課程基本資料——`get_detail` 用它覆蓋活表那一份（#720）。

    ⚠️ 刻意**不含 `status`**：狀態轉換不走暫存（理由見 `COURSE_SYSTEM_FIELDS`）。
    少一個欄位是刻意的，不是漏寫。
    """

    course_name: str
    description: str | None
    open_start_at: datetime | None
    open_end_at: datetime | None
    require_approval: bool
    version: int
    audiences: list[AudiencePair]


class EtCourseService:
    """課程骨架與章節編排。"""

    def __init__(
        self,
        courses: EtCourseRepository | None = None,
        tags: EtCourseTagRepository | None = None,
        chapters: EtChapterRepository | None = None,
        items: EtItemRepository | None = None,
        materials: EtMaterialRepository | None = None,
        quizzes: EtQuizRepository | None = None,
        audit: AuditLogService | None = None,
        tag_invite: EtTagInviteRepository | None = None,
        invite_mailer: CourseInviteMailer | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        course_update_mailer: CourseUpdateMailer | None = None,
        publish: EtPublishService | None = None,
        stage_writer: EtCourseStageWriter | None = None,
        stage: EtCourseStageRepository | None = None,
    ) -> None:
        self._courses = courses or EtCourseRepository()
        self._tags = tags or EtCourseTagRepository()
        self._chapters = chapters or EtChapterRepository()
        self._items = items or EtItemRepository()
        self._materials = materials or EtMaterialRepository()
        self._quizzes = quizzes or EtQuizRepository()
        self._audit = audit or AuditLogService()
        self._tag_invite = tag_invite or EtTagInviteRepository()
        self._invite_mailer = invite_mailer or CourseInviteMailer()
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._course_update_mailer = course_update_mailer or CourseUpdateMailer()
        self._stage_writer = stage_writer or EtCourseStageWriter()
        self._stage = stage or EtCourseStageRepository()
        # #301：`update_basic` 需要發布六項檢核（`_evaluate` 在 publish service——它要組快照
        # 並問 DM 廢止狀態）。單向依賴：publish service 不反向引用本類別。
        self._publish = publish or EtPublishService()

    # ── 課程 ────────────────────────────────────────────────────────────────

    async def create_draft(
        self, db: AsyncSession, req: CourseCreateReq, *, operator: OperatorInfo
    ) -> CourseCreateResult:
        """建立草稿課程並掛上受訓單位標籤。

        `OWNER_ID` 取自操作者，**不由請求帶入**——否則教師可代他人建立課程並繞過
        擁有權判定。呼叫端（router）須先以 `require_et_roles(ROLE_TEACHER)` 把關。
        """
        desired = _pairs_of(req)
        await self._ensure_pairs_selectable(db, desired)
        course = await self._courses.create_draft(
            db,
            {
                "course_name": req.course_name,
                "description": req.description,
                "open_start_at": req.open_start_at,
                "open_end_at": req.open_end_at,
                "require_approval": req.require_approval,
                "owner_id": operator.user_id,
            },
            operator,
        )
        if desired:
            await self._tags.apply(db, course.course_id, to_add=desired, to_remove=set(), operator=operator)
        # 章節於同一交易內一併建立——使新增流程不必「先存草稿才能加章節」
        for name in req.chapters:
            await self._chapters.append(db, course.course_id, name, operator)
        await self._log(db, "CREATE", operator.user_id, course.course_id, "建立課程草稿")
        return CourseCreateResult(course_id=course.course_id, version=course.version)

    async def list_courses(
        self,
        db: AsyncSession,
        *,
        actor_id: str,
        scope: str,
        keyword: str | None,
        tag_id: int | None,
        unit_tag_id: int | None = None,
        owner_id: str | None,
        page: int,
        limit: int,
    ) -> PaginatedResult[CourseCard]:
        """ET01 課程清單（`FR-ET-US7-01`~`-04`）。

        ## 為何分兩段：先 `paginate()`，再批次補齊

        `paginate()` 以 `result.scalars()` 取結果，**只拿第一欄**——聚合值塞進同一個
        select 會被靜默丟掉。故清單查詢只選 `EtCourse`，章節數 / 學員數 / 標籤 /
        建立者姓名以**該頁的 `course_id`** 批次補齊：三次固定成本的查詢，與頁面筆數無關。

        分頁一律走 `core/pagination.paginate()`（專案規範），不自行拼 offset/limit。

        ## `now` 只取一次

        過濾（`build_list_stmt`）與每張卡片的 `is_closed` 必須以**同一個時點**判定。各自
        呼叫 `utcnow()` 會在跨越 `OPEN_END_AT` 的那一瞬間產生自相矛盾的回應——課程被列
        進「全部課程」，卡片卻標著「已關閉」。
        """
        now = utcnow()
        stmt = self._courses.build_list_stmt(
            actor_id=actor_id,
            scope=scope,
            keyword=keyword,
            tag_id=tag_id,
            unit_tag_id=unit_tag_id,
            owner_id=owner_id,
            now=now,
        )
        paged = await paginate(db, stmt, page=page, limit=limit, schema=CourseRow)
        rows: list[CourseRow] = paged["data"]
        course_ids = [r.course_id for r in rows]

        counts = await self._courses.counts_by_course(db, course_ids)
        pairs = await self._courses.pairs_by_course(db, course_ids)
        owner_names = await self._owner_names(db, {r.owner_id for r in rows})

        cards = [
            CourseCard(
                course_id=r.course_id,
                course_name=r.course_name,
                status=r.status,
                open_start_at=r.open_start_at,
                open_end_at=r.open_end_at,
                owner_id=r.owner_id,
                owner_name=owner_names.get(r.owner_id, (None, False))[0],
                owner_is_disabled=owner_names.get(r.owner_id, (None, False))[1],
                audiences=[AudiencePair(**p._asdict()) for p in pairs.get(r.course_id, [])],
                chapter_count=counts.get(r.course_id, (0, 0))[0],
                student_count=counts.get(r.course_id, (0, 0))[1],
                # **由後端判定**——前端自行比對 owner_id 等於把授權語意複製一份到瀏覽器
                is_owner=r.owner_id == actor_id,
                # 期間已過者 `status` 仍是 `PUBLISHED`（自動轉 `CLOSED` 屬未實作的
                # ET-16），前端若自己判 `status` 會把它標成「已發布」
                is_closed=is_effectively_closed(status=r.status, open_end_at=r.open_end_at, now=now),
            )
            for r in rows
        ]
        return {"data": cards, "meta": paged["meta"]}

    async def list_filter_owners(
        self,
        db: AsyncSession,
        *,
        actor_id: str,
        keyword: str | None,
        tag_id: int | None,
        unit_tag_id: int | None,
    ) -> list[OwnerOption]:
        """ET01「全部課程」建立者下拉的選項（#648）。

        原本前端由**當頁的 12 張卡片**推導選項：課程全落在第 2 頁以後的教師不會出現，
        翻頁時選項也跟著變。改由本支取「全部課程」整個母體的建立者，不分頁。

        母體條件見 `EtCourseRepository.list_owner_ids`（與清單共用同一個查詢）。依姓名
        排序，查無姓名者（`DP_USER` 無此列）排最後。

        Args:
            actor_id: 呼叫者（排除其已在籍之課程，與清單一致）。
            keyword: 課程名稱關鍵字；與 `tag_id`、`unit_tag_id` 同清單的篩選條件。

        Returns:
            建立者選項清單。
        """
        owner_ids = await self._courses.list_owner_ids(
            db, actor_id=actor_id, keyword=keyword, tag_id=tag_id, unit_tag_id=unit_tag_id, now=utcnow()
        )
        names = await self._owner_names(db, set(owner_ids))
        options = []
        for owner_id in owner_ids:
            name, disabled = names.get(owner_id, (None, False))
            options.append(OwnerOption(owner_id=owner_id, owner_name=name, owner_is_disabled=disabled))
        return sorted(options, key=lambda o: (o.owner_name is None, o.owner_name or "", o.owner_id))

    async def list_filter_tags(self, db: AsyncSession) -> list[TagOption]:
        """篩選下拉的標籤來源：**全部含停用者**（與 ET05 編輯用的 `list_tag_options` 相反）。

        停用標籤若排除，掛著它的歷史課程就從此搜不到，而畫面上不會有任何異常。
        """
        return [TagOption.model_validate(t) for t in await self._courses.list_all_tags(db)]

    async def _owner_names(self, db: AsyncSession, owner_ids: set[str]) -> dict[str, tuple[str, bool]]:
        """`{user_id: (user_name, 帳號是否已停用)}`——**一次查回整頁**，不逐筆。

        唯讀查詢 `DP_USER`，屬 `spec.md` §外模組 table 引用清單 A 之既有例外（US7 已列）。

        ## 三種狀態，不可混為兩種（#330）

        | 情況 | 回傳 | 畫面 |
        |---|---|---|
        | 帳號正常 | `(姓名, False)` | `王大明` |
        | 帳號已停用 | `(姓名, True)` | `王大明（已停用帳號）` |
        | 查無此列（含 `DELETED=1`）| 不在 key 裡 → 呼叫端拿 `(None, False)` | `—` |

        第三種代表 `DP_USER` 根本沒有這個人（資料不一致），與「停用」是兩回事；混用會讓
        真正的資料問題被當成正常狀態而永遠沒人查。

        ## 🔴 停用讀的是 `STATUS`，**不是 `DELETED`**

        EDMS **沒有刪除使用者的功能**——`dp/users/router.py` 只有 `PATCH /{id}/status`，
        全 repo 沒有任何 code path 會把 `DP_USER.DELETED` 設成 1。離職 / 轉調的實際處理
        是停用（`STATUS='DISABLED'`），SCHDP001 閒置 90 天也是寫同一欄。

        本支最初讀 `DELETED`，那個旗標在正式環境恆為 `False`，畫面上
        永遠不會出現標記。改讀 `STATUS` 後才真的涵蓋交接情境。

        判定委派 `dp.users.account_status.is_account_disabled()`——該模組明訂「`STATUS`
        值域屬 DP 語意，其他模組不得自行解讀」，在這裡寫 `== "DISABLED"` 會讓 DP 日後
        新增第三種狀態時，ET 靜默地把它算成「未停用」。

        ## 為何不濾掉停用者

        本支原本帶 `DELETED == 0` 且不回停用資訊，於是停用擁有者的課程在卡片上顯示
        「—」、在建立者下拉顯示 `owner_id`、而詳細頁（另一條沒過濾的查詢）顯示姓名——
        同一個人三種身份。擁有者停用代表**沒有人能編輯這門課、需要交接**，姓名是交接
        資訊；揭露對象限 `require_et_roles(ET_TEACHER, ET_ADMIN)`，即交接情境本身的對象。
        """
        if not owner_ids:
            return {}
        rows = (
            await db.execute(
                select(DpUser.user_id, DpUser.user_name, DpUser.status).where(
                    DpUser.user_id.in_(owner_ids), DpUser.deleted == 0
                )
            )
        ).all()
        return {user_id: (name, is_account_disabled(status)) for user_id, name, status in rows}

    async def get_detail(self, db: AsyncSession, course_id: int, *, actor_id: str) -> CourseDetail:
        """課程詳細（含章節與標籤）。他人課程可閱覽，以 `is_owner` 表達可否編輯。"""
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        # 共用 `_owner_names()`——本支原本自己寫一條沒有 `DELETED` 判斷的查詢，正是
        # #330 那三種答案不一致的源頭。兩條查詢分開維護，遲早再分岔一次。
        owner_name, owner_is_disabled = (await self._owner_names(db, {course.owner_id})).get(
            course.owner_id, (None, False)
        )
        pairs = (await self._courses.pairs_by_course(db, [course_id]))[course_id]
        is_owner = course.owner_id == actor_id
        # 🔴 **只有擁有者看得到暫存版本。**
        #
        # 他人閱覽（`is_owner=False`）與學員端一律看**已生效版本**——他們不是在編輯，
        # 給他們看一份還沒生效的內容會讓「這門課有什麼」出現兩種答案。
        #
        # ⚠️ 還沒編輯過（`has_stage` 為假）時讀活表：此時兩者內容相同，但讀活表才能拿到
        # 正確的 `VERSION`（暫存列還不存在，而前端要用它做樂觀鎖）。
        staged_chapters = None
        if is_owner and is_staged(course) and await self._stage.has_stage(db, course_id):
            staged_chapters = await self._staged_chapter_items(db, course_id)

        if staged_chapters is None:
            chapters = await self._chapters.list_by_course(db, course_id)
            items_by_chapter = await self._items_by_chapter(db, [c.chapter_id for c in chapters])
        # 🔴 **基本資料、受訓對象與 `VERSION` 跟著章節一起換邊（#720）。**
        #
        # 換邊的條件完全相同（`staged_chapters is not None`），所以不另外再查一次條件——
        # 兩個條件分開寫就會分岔，而分岔的症狀是「章節讀暫存、課名讀活表」：教師改了
        # 課名按儲存、重整後看到舊課名，以為沒存到。
        #
        # 🔴 `VERSION` 尤其要換。暫存開始之後活表的版本就不再遞增（基本資料與重排都打在
        # 暫存列上），回活表的值會讓第二次存檔恆 409——而重整拿到的還是同一個數字，
        # 教師永遠存不進去。
        #
        # ⚠️ `status` 仍取活表：狀態轉換（發布 / 關閉 / 再開課）不走暫存，
        # 理由見 `COURSE_SYSTEM_FIELDS`。
        basic = await self._staged_basic(db, course_id) if staged_chapters is not None else None
        return CourseDetail(
            course_id=course.course_id,
            course_name=basic.course_name if basic else course.course_name,
            description=basic.description if basic else course.description,
            status=course.status,
            open_start_at=basic.open_start_at if basic else course.open_start_at,
            open_end_at=basic.open_end_at if basic else course.open_end_at,
            require_approval=basic.require_approval if basic else course.require_approval,
            version=basic.version if basic else course.version,
            owner_id=course.owner_id,
            owner_name=owner_name,
            owner_is_disabled=owner_is_disabled,
            is_owner=is_owner,
            audiences=basic.audiences if basic else [AudiencePair(**p._asdict()) for p in pairs],
            # 僅 owner 可見（#247）：學員角色人人都有，對所有人回傳等於讓任何登入者
            # 收集全站邀請碼、自行加入任意課程，繞過 ET-4 的邀請門檻與限流。
            invitation_code=course.invitation_code if is_owner else None,
            # 暫存區有東西 ＝ 有尚未按下「更新」的編輯。`staged_chapters is not None`
            # 正是那個條件（擁有者 + 已發布 + 有暫存），不另外再查一次。
            has_pending_changes=staged_chapters is not None,
            chapters=staged_chapters
            if staged_chapters is not None
            else [
                ChapterItem(
                    chapter_id=c.chapter_id,
                    chapter_name=c.chapter_name,
                    sort_order=c.sort_order,
                    version=c.version,
                    items=items_by_chapter.get(c.chapter_id, []),
                )
                for c in chapters
            ],
        )

    async def _staged_chapter_items(self, db: AsyncSession, course_id: int) -> list[ChapterItem]:
        """把暫存樹組成編輯頁要的章節 / 項目清單。

        ⚠️ **id 一律走 `exposed_id`**：既有內容回活表 id（與今天相同），本次編輯新增的回
        負數。前端把哪個數字帶回 PUT，決定了後端會改到哪一邊——回錯了不會報錯，只會
        改到別的東西（見 `stage_writer.exposed_id`）。

        ⚠️ `version` 回的是**暫存列自己的**，不是活表那一列的。兩者的計數在 seed 之後
        就分岔了。
        """
        nodes = await self._stage.load_tree(db, course_id)
        by_parent: dict[int | None, list] = {}
        for n in nodes:
            by_parent.setdefault(n.parent_stage_id, []).append(n)

        def children(parent: int | None, entity_type: str) -> list:
            return sorted(
                (n for n in by_parent.get(parent, []) if n.entity_type == entity_type),
                key=lambda n: (n.sort_order, n.stage_id),
            )

        result: list[ChapterItem] = []
        for chapter in children(None, ENTITY_CHAPTER):
            items: list[ItemRow] = []
            for item in children(chapter.stage_id, ENTITY_ITEM):
                material = children(item.stage_id, ENTITY_MATERIAL)
                quiz = children(item.stage_id, ENTITY_QUIZ)
                content = (material or quiz or [None])[0]
                title = ""
                if content is not None:
                    title = str(content.payload.get("material_name") or content.payload.get("quiz_name") or "")
                items.append(
                    ItemRow(
                        item_id=exposed_id(source_id=item.source_id, stage_id=item.stage_id),
                        item_type=str(item.payload.get("item_type") or ""),
                        title=title,
                        sort_order=item.sort_order,
                        material_id=(
                            exposed_id(source_id=material[0].source_id, stage_id=material[0].stage_id)
                            if material
                            else None
                        ),
                        quiz_id=(exposed_id(source_id=quiz[0].source_id, stage_id=quiz[0].stage_id) if quiz else None),
                        version=item.version,
                        question_count=len(children(quiz[0].stage_id, ENTITY_QUESTION)) if quiz else None,
                    )
                )
            result.append(
                ChapterItem(
                    chapter_id=exposed_id(source_id=chapter.source_id, stage_id=chapter.stage_id),
                    chapter_name=str(chapter.payload.get("chapter_name") or ""),
                    sort_order=chapter.sort_order,
                    version=chapter.version,
                    items=items,
                )
            )
        return result

    async def update_basic(
        self, db: AsyncSession, course_id: int, req: CourseUpdateReq, *, operator: OperatorInfo
    ) -> None:
        """更新基本資料與標籤（全量覆寫）。

        已發布 / 已關閉課程寫**暫存區**（#720），按「更新」才生效；草稿直接寫活表。

        Raises:
            AppError: 404 `ET_COURSE_001`；403 `ET_COURSE_002`；409 `ET_LOCK_001` 版本不符；
                422 `ET_PUBLISH_001` 本次延期會讓一門視同關閉的課程復活、但六項檢核未通過
                （#301，見 `EtPublishService.ensure_revival_publishable`；**僅草稿路徑**，
                暫存路徑的檢核改在「更新」當下以暫存值重跑）。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        current = await self._tags.list_pairs(db, course_id)
        desired = _pairs_of(req)
        # ⚠️ `current` 取**活表**而非暫存，連暫存路徑也是。FR-ET-US3-02 擋的是「移除學員
        # 已經看得到的受訓對象」，而學員看得到的就是活表那一份；教師本次自己加進暫存、
        # 還沒按「更新」就又拿掉的配對沒有任何人看過，不該被擋。
        ensure_tag_change_allowed(course.status, current=current, desired=desired)
        # #301：擋「清空訖止」——全量覆寫表單少送一個欄位就會讓課程永久不再視同關閉。
        # 放在復活檢核之前：清空是要直接擋下的動作，不是「檢核通過就放行」的延期。
        ensure_schedule_not_cleared(course.status, current_end_at=course.open_end_at, desired_end_at=req.open_end_at)
        await self._ensure_pairs_selectable(db, desired - current)

        if is_staged(course):
            # 🔴 **#720：基本資料與受訓對象進暫存，活表一個欄位都不動。**
            #
            # 2026-10-19 手測回報的第一個 bug 就在這裡：教師改完基本資料按「儲存」，
            # 學員當場就看到了尚未更新的內容。
            #
            # ⚠️ 這裡**刻意不做**三件事，它們全部以「活表變成什麼」為前提，而此刻活表
            # 沒變：
            #
            # | 不做的事 | 改在哪裡做 |
            # |---|---|
            # | 復活檢核（`ensure_revival_publishable`）| 「更新」當下，以暫存值重跑 |
            # | 復活時帶入全部配對 | 套用之後（`apply_stage`）|
            # | 新增配對補帶入與邀請信 | 套用之後（裁示 2026-10-19：延到「更新」當下）|
            #
            # 在這裡做的症狀是**寄出不存在的事實**：教師加了一組配對就先收到邀請信，
            # 但他按「取消」離開，那門課從頭到尾沒有那組配對——而信已經寄出去了。
            await self._stage_writer.lock_course(db, course_id)
            await self._stage_writer.ensure_seeded(db, course_id, operator)
            await self._stage_basic(db, course_id, req, desired=desired, operator=operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "編輯課程基本資料（暫存）")
            return

        # 🔴 **到這裡課程必為草稿。**`is_staged` 的判準是 `!= COURSE_DRAFT`，上面的分支
        # 已把已發布與已關閉全部接走。
        #
        # ⇒ #301 的復活檢核與 #678 / #273 的補帶入在這條路徑上**已成死碼**，因此搬走而
        # 不是留著：草稿不可能「復活」（`ensure_revival_publishable` 的第一個條件就是
        # 狀態為 `PUBLISHED`），也不會補帶入（`course.status == COURSE_PUBLISHED` 恆假）。
        # 留著會讓下一個人以為這裡還管著那些事，而它們真正發生的地方是
        # `EtPublishService.update_published`（套用暫存之後）。
        rowcount = await self._courses.update_basic(
            db,
            course_id,
            req.version,
            {
                "course_name": req.course_name,
                "description": req.description,
                "open_start_at": req.open_start_at,
                "open_end_at": req.open_end_at,
                "require_approval": req.require_approval,
            },
            operator,
        )
        ensure_version_matched(rowcount=rowcount, entity="ET_COURSE")
        await self._tags.apply(db, course_id, to_add=desired - current, to_remove=current - desired, operator=operator)
        await self._log(db, "UPDATE", operator.user_id, course_id, "編輯課程基本資料")

    async def _staged_basic(self, db: AsyncSession, course_id: int) -> _StagedBasic | None:
        """詳細頁要顯示的「編輯中的基本資料」（#720）。呼叫端已確認有暫存區。

        ⚠️ payload 以 `[]` 取而非 `.get()`：五個欄位是 seed 時一起寫進去的，缺了任何一個
        代表這棵樹是 #720 之前的舊結構。`.get()` 會把那件事變成「課名顯示空白」，
        KeyError 至少指得出是哪一欄。
        """
        node = await self._stage_writer.course_node(db, course_id)
        if node is None:  # pragma: no cover - 呼叫端已以 `has_stage` 確認
            return None
        tags = await self._stage_writer.children_of(db, course_id, ENTITY_COURSE_TAG, node.stage_id)
        pairs = await self._courses.labels_for_pairs(
            db, [(t.payload["unit_tag_id"], t.payload["tag_id"]) for t in tags]
        )
        return _StagedBasic(
            course_name=node.payload["course_name"],
            description=node.payload["description"],
            open_start_at=node.payload["open_start_at"],
            open_end_at=node.payload["open_end_at"],
            require_approval=node.payload["require_approval"],
            version=node.version,
            audiences=[AudiencePair(**p._asdict()) for p in pairs],
        )

    async def _stage_basic(
        self,
        db: AsyncSession,
        course_id: int,
        req: CourseUpdateReq,
        *,
        desired: set[Pair],
        operator: OperatorInfo,
    ) -> None:
        """把基本資料與受訓對象寫進暫存課程節點（#720）。呼叫端須已 `lock_course` 並 seed。

        🔴 受訓對象走**逐筆比對**，不是砍光重建。請求是全量覆寫，砍光重建寫起來短得多，
        但那會讓每個暫存配對的 `SOURCE_ID` 都變成 `None`，而 `None` 的語意是「活表還沒有
        這一列」。三件事會同時壞掉：

        1. `_delete_removed` 看不到任何 `SOURCE_ID` 指著既有的 `ET_COURSE_TAG` 列
           ⇒ 把**全部**既有配對當成「教師刪了它」而軟刪
        2. `_upsert` 把每一組都當新列插入 ⇒ 與上一條在同一個交易裡撞唯一鍵
        3. 「本次新增了哪幾組」分不出來 ⇒ 補邀請信會寄給**全部**對象，包含早就在課程裡的人

        逐筆比對要先建一份鍵對照表（配對沒有自己的識別碼，`TAG_ID` × `UNIT_TAG_ID` 才是鍵），
        多那幾行換掉上面三件事。

        ⚠️ 樂觀鎖檢核的是**暫存課程節點**的 `VERSION`，與 `reorder_chapters` 同一個令牌
        （理由見 `stage_writer.course_node`）。
        """
        node = await self._stage_writer.course_node(db, course_id)
        if node is None:  # pragma: no cover - `ensure_seeded` 必定建出課程節點
            raise ValueError("暫存樹缺少課程節點（COURSE）")
        rowcount = await self._stage_writer.update_payload(
            db,
            node.stage_id,
            version=req.version,
            # 🔴 **五個欄位一個都不能少。**`update_payload` 是整份取代，而 `_upsert` 的規則
            # 是「payload 裡沒有的欄位就不碰活表」——漏送一個的症狀是教師改了它、按「更新」
            # 卻靜默保留舊值，畫面上沒有任何訊息。這五個正是 `COURSE_PAYLOAD_FIELDS`。
            payload={
                "course_name": req.course_name,
                "description": req.description,
                "open_start_at": req.open_start_at,
                "open_end_at": req.open_end_at,
                "require_approval": req.require_approval,
            },
            operator=operator,
        )
        ensure_version_matched(rowcount=rowcount, entity=_STAGE_ENTITY)
        staged = {
            (t.payload["unit_tag_id"], t.payload["tag_id"]): t
            for t in await self._stage_writer.children_of(db, course_id, ENTITY_COURSE_TAG, node.stage_id)
        }
        for pair, tag in staged.items():
            if pair not in desired:
                await self._stage_writer.delete_subtree(db, tag.stage_id, operator)
        # 排序讓同一份 `desired` 每次產生相同的 `SORT_ORDER`，否則 set 的迭代順序會讓
        # 暫存列的順序隨機浮動，比對兩次編輯的差異時看起來像「每次都改了東西」。
        for unit_tag_id, tag_id in sorted(desired - set(staged)):
            await self._stage_writer.append(
                db,
                course_id,
                ENTITY_COURSE_TAG,
                parent_stage_id=node.stage_id,
                payload={"tag_id": tag_id, "unit_tag_id": unit_tag_id},
                operator=operator,
            )

    async def delete_draft(self, db: AsyncSession, course_id: int, *, operator: OperatorInfo) -> None:
        """刪除草稿課程（SA 裁示 Q1）：本體與其下章節 / 項目一併軟刪。

        已發布 / 已關閉課程改用 US11 之「關閉」——`ensure_deletable` 以
        `ET_COURSE_005` 擋下。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        ensure_deletable(course.status)
        chapters = await self._chapters.list_by_course(db, course_id)
        await self._chapters.soft_delete_with_cascade(db, [c.chapter_id for c in chapters], operator)
        await self._courses.soft_delete(db, course_id, operator)
        await self._log(db, "DELETE", operator.user_id, course_id, "刪除草稿課程")

    # ── 章節 ────────────────────────────────────────────────────────────────

    async def add_chapter(
        self, db: AsyncSession, course_id: int, req: ChapterCreateReq, *, operator: OperatorInfo
    ) -> ChapterItem:
        """新增章節，追加至最末；**已發布課程另通知在籍學員**（ET-13 / #303）。

        ## 為何通知掛在這裡而不是新開一支端點

        `spec_us3` 場景 29 的觸發條件就是「已發布課程新增章節」——那即是本方法。獨立
        端點會讓「新增了章節但忘記通知」成為可能，而那個漏失沒有任何地方會察覺。

        ## 草稿不通知

        草稿對學員不可見、也不會有 enrollment。判定看**課程狀態**而非「有沒有人」——
        後者在資料異常（草稿卻有選課列）時會寄出一封指向學員進不去的課程的信。

        ## 寄信失敗不影響章節

        `EtNotifier` 於唯一出口吞掉 `AppError`（見其 docstring）：管理者停用範本或收件人
        超上限時，章節仍然建立成功。本方法**不因寄信結果改變任何回傳值**。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if is_staged(course):
            # 取課程行鎖後才碰暫存區（理由見 `stage_writer.lock_course`）
            await self._stage_writer.lock_course(db, course_id)
            # 🔴 已發布 / 已關閉：寫進暫存區，學員看到的仍是上一次「更新」的版本（#631）。
            #
            # ⛔ **不在這裡寄 `COURSE_UPDATE` 通知**——信裡寫的是「課程內容有更新」，
            # 而此刻學員看不到任何變化，那句話是假的。通知延到「更新」當下（PR 2c）。
            stage_id = await self._stage_writer.append(
                db,
                course_id,
                ENTITY_CHAPTER,
                parent_stage_id=None,
                payload={"chapter_name": req.chapter_name},
                operator=operator,
            )
            await self._log(db, "CREATE", operator.user_id, course_id, "新增章節（暫存）")
            # 🔴 **負數**——它還不存在於活表（見 `stage_writer.exposed_id`）。
            # 回正數的話前端下一步會拿它去打 `/chapters/{id}/items`，而那支會把它
            # 當活表 id 查 `ET_CHAPTER` ⇒ 404，或更糟：撞上某個真實章節。
            return ChapterItem(chapter_id=-stage_id, chapter_name=req.chapter_name, sort_order=0, version=0)

        # 🔴 **到得了這裡的只有草稿課程**（`is_staged` 已於上方 return）。
        #
        # 原本這裡有一道 `if course.status == COURSE_PUBLISHED: 寄 COURSE_UPDATE`，
        # #631 之後**永遠不成立**——已發布課程走的是暫存路徑。留著那個永遠為假的條件，
        # 下一個人讀到會以為通知還掛在這裡，而實際上它已經移到
        # `publish_service.update_published`（套用成功之後才寄，信的內容那時才成立）。
        #
        # ⛔ 不要把它加回來：在新增當下寄信，信裡那句「課程新增了章節」對學員是假的。
        chapter = await self._chapters.append(db, course_id, req.chapter_name, operator)
        # ⚠️ 稽核**刻意排在通知之後**：`AuditLogService.log_action` 會取
        # `pg_advisory_xact_lock`，而那是**交易層級**鎖——持有到整個外層交易 commit 為止
        # （見 `dp/audit/repository.acquire_chain_lock` 的 docstring）。若先寫稽核，接下來
        # 逐人寄信的 N 次查詢全程都握著**全平台唯一**的稽核鏈鎖，期間任何人的登入、DM
        # 送審、DP 帳號異動的稽核寫入都得排隊。
        #
        # 該 docstring 自己寫了「因會呼叫稽核的情境頻率不高，可接受；若未來高頻呼叫需
        # 縮小臨界區再評估」——本路徑正是它預留的那個情況。順序一換，鎖的持有時間就只
        # 剩 commit 本身。
        await self._log(db, "CREATE", operator.user_id, course_id, "新增章節")
        return ChapterItem.model_validate(chapter)

    async def rename_chapter(
        self, db: AsyncSession, chapter_id: int, req: ChapterRenameReq, *, operator: OperatorInfo
    ) -> None:
        """更名章節（樂觀鎖檢核章節自身之 `VERSION`）。

        已發布 / 已關閉課程寫暫存區（#631）；樂觀鎖改檢核**暫存列自己的** `VERSION`。
        """
        ref, course_id = await self._staged_chapter(db, chapter_id, operator.user_id, operator)
        if ref is not None:
            rowcount = await self._stage_writer.update_payload(
                db, ref.stage_id, version=req.version, payload={"chapter_name": req.chapter_name}, operator=operator
            )
            ensure_version_matched(rowcount=rowcount, entity=_STAGE_ENTITY)
            await self._log(db, "UPDATE", operator.user_id, course_id, "更名章節（暫存）")
            return

        chapter = await self._chapters.get(db, chapter_id)
        rowcount = await self._chapters.rename(db, chapter_id, req.version, req.chapter_name, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_CHAPTER")
        await self._log(db, "UPDATE", operator.user_id, chapter.course_id, "更名章節")

    async def reorder_chapters(
        self, db: AsyncSession, course_id: int, req: ChapterReorderReq, *, operator: OperatorInfo
    ) -> None:
        """重排章節順序。

        **以課程層 `VERSION` 保護**，非章節層——重排改動的是課程結構（多列同時變動），
        且若遞增各章節之 `VERSION`，正在改章節名的另一裝置會無故衝突，違反
        FR-ET-US3-15「不同實體並行編輯互不衝突」。
        """
        course = await self._require_owned(db, course_id, operator.user_id)
        if is_staged(course):
            # 取課程行鎖後才碰暫存區（理由見 `stage_writer.lock_course`）
            await self._stage_writer.lock_course(db, course_id)
            await self._stage_writer.ensure_seeded(db, course_id, operator)
            # 🔴 併發令牌是**暫存**課程節點的 `VERSION`，不是活表的。
            #
            # #631 當時這裡遞增的是活表 `ET_COURSE.VERSION`，理由寫著「課程列不是內容、
            # 不在 `load_live_tree` 的範圍內」。**#720 把課程本體搬進暫存樹之後那句話不再
            # 成立**——課程列現在就在那棵樹裡，遞增活表版本就成了「已發布課程的內容編輯
            # 動到了學員看得到的那張表」，由 `test_已發布課程的內容編輯不得直接寫活表`
            # 當場抓出來。
            #
            # ⚠️ 語意沒有變：課程層的令牌一樣同時保護基本資料與重排（#720 之前兩者都打在
            # `ET_COURSE.VERSION` 上，所以兩人同時改一樣會衝突），只是改記在暫存列。
            course_node = await self._stage_writer.course_node(db, course_id)
            if course_node is None:  # pragma: no cover - `ensure_seeded` 必定建出課程節點
                raise ValueError("暫存樹缺少課程節點（COURSE）")
            nodes = await self._stage_writer.children_of(db, course_id, ENTITY_CHAPTER, None)
            by_exposed = {exposed_id(source_id=n.source_id, stage_id=n.stage_id): n.stage_id for n in nodes}
            ensure_reorder_complete(current_ids=set(by_exposed), requested=req.chapter_ids)
            rowcount = await self._stage_writer.bump_version(db, course_node.stage_id, req.version, operator)
            ensure_version_matched(rowcount=rowcount, entity=_STAGE_ENTITY)
            await self._stage_writer.apply_order(db, [by_exposed[i] for i in req.chapter_ids], operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "調整章節順序（暫存）")
            return

        current = await self._chapters.list_by_course(db, course_id)
        ensure_reorder_complete(current_ids={c.chapter_id for c in current}, requested=req.chapter_ids)
        rowcount = await self._courses.bump_version(db, course_id, req.version, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_COURSE")
        await self._chapters.apply_order(db, resequence(req.chapter_ids), operator)
        await self._log(db, "UPDATE", operator.user_id, course_id, "調整章節順序")

    async def delete_chapter(self, db: AsyncSession, chapter_id: int, *, operator: OperatorInfo) -> None:
        """刪除章節：本體、其下項目與教材 / 測驗內容、學員紀錄**皆軟刪**，剩餘章節順序遞補。

        已發布 / 已關閉課程只移除**暫存**子樹（#631）——學員紀錄要到「更新」套用時才由
        `stage_apply._DELETERS` 連帶處理，此刻一筆都不動。
        """
        ref, course_id = await self._staged_chapter(db, chapter_id, operator.user_id, operator)
        if ref is not None:
            await self._stage_writer.delete_subtree(db, ref.stage_id, operator)
            await self._log(db, "DELETE", operator.user_id, course_id, "刪除章節（暫存）")
            return

        chapter = await self._chapters.get(db, chapter_id)
        await self._chapters.soft_delete_with_cascade(db, [chapter_id], operator)
        await self._chapters.resequence_remaining(db, chapter.course_id, operator)
        await self._log(db, "DELETE", operator.user_id, chapter.course_id, "刪除章節")

    # ── 章節項目（#203）──────────────────────────────────────────────────────

    async def add_item(
        self, db: AsyncSession, chapter_id: int, req: ItemCreateReq, *, operator: OperatorInfo
    ) -> ItemRow:
        """新增章節項目（教材 / 測驗），追加至最末。

        **同一交易內**一併建立對應之空殼 `ET_MATERIAL` / `ET_QUIZ`：使用者於 UI 是
        「新增項目 → 教材」一個動作，若拆成兩次請求，中途失敗會留下指不到任何內容的
        項目（而 `CK_ET_ITEM_TYPE_TARGET` 根本不允許該狀態）。

        空殼當下三類媒材皆空，這**不違反**「教材至少擇一媒材」——該檢核在儲存教材
        內容時才套用（`ET_MATERIAL_002`），不在建立時。
        """
        ref, course_id = await self._staged_chapter(db, chapter_id, operator.user_id, operator)
        if ref is not None:
            # 🔴 暫存模式下**項目與其教材 / 測驗是兩個節點**，後者掛在前者底下
            # （`stage_entities` 的 `LINK_PARENT_FK`：活表是 `ET_ITEM.MATERIAL_ID`
            # 反向指著教材，套用時才建立那個連結）。
            item_stage = await self._stage_writer.append(
                db,
                course_id,
                ENTITY_ITEM,
                parent_stage_id=ref.stage_id,
                payload={"item_type": req.item_type},
                operator=operator,
            )
            if req.item_type == ITEM_MATERIAL:
                child = await self._stage_writer.append(
                    db,
                    course_id,
                    ENTITY_MATERIAL,
                    parent_stage_id=item_stage,
                    payload={"material_name": req.title, "description_html": None},
                    operator=operator,
                )
                material_id, quiz_id = -child, None
            else:
                child = await self._stage_writer.append(
                    db,
                    course_id,
                    ENTITY_QUIZ,
                    parent_stage_id=item_stage,
                    payload={
                        "quiz_name": req.title,
                        "description": None,
                        "pass_score": DEFAULT_PASS_SCORE,
                        "time_limit_min": None,
                        "max_retry": DEFAULT_MAX_RETRY,
                    },
                    operator=operator,
                )
                material_id, quiz_id = None, -child
            await self._log(db, "CREATE", operator.user_id, course_id, f"新增章節項目（{req.item_type}，暫存）")
            return ItemRow(
                item_id=-item_stage,
                item_type=req.item_type,
                title=req.title,
                sort_order=0,
                material_id=material_id,
                quiz_id=quiz_id,
                version=0,
                question_count=0 if req.item_type != ITEM_MATERIAL else None,
            )

        chapter = await self._require_owned_chapter(db, chapter_id, operator.user_id)
        # 名稱必填（#414）——前端 `NewItemDialog` 於建立**之前**取得，見 `ItemCreateReq` docstring
        if req.item_type == ITEM_MATERIAL:
            material = await self._materials.create_shell(db, req.title, operator)
            item = await self._items.append(
                db, chapter_id, item_type=req.item_type, material_id=material.material_id, operator=operator
            )
        else:
            quiz = await self._quizzes.create_shell(db, req.title, operator)
            item = await self._items.append(
                db, chapter_id, item_type=req.item_type, quiz_id=quiz.quiz_id, operator=operator
            )
        await self._log(db, "CREATE", operator.user_id, chapter.course_id, f"新增章節項目（{req.item_type}）")
        return ItemRow(
            item_id=item.item_id,
            item_type=item.item_type,
            title=req.title,
            sort_order=item.sort_order,
            material_id=item.material_id,
            quiz_id=item.quiz_id,
            version=item.version,
            # 剛建立的測驗必然是 0 題（`create_shell`）——與列表路徑一致地回報，
            # 否則新增測驗後畫面要等重新整理才看得到「尚無題目」的警示。
            question_count=0 if req.item_type != ITEM_MATERIAL else None,
        )

    async def reorder_items(
        self, db: AsyncSession, chapter_id: int, req: ItemReorderReq, *, operator: OperatorInfo
    ) -> None:
        """重排章節內項目順序（送完整陣列；帶**章節層** `version`）。

        以章節版本保護而非項目版本——理由同章節重排以課程版本保護：順序是上一層的
        結構，且遞增各項目版本會讓正在編輯該教材的另一裝置無故衝突。
        """
        ref, course_id = await self._staged_chapter(db, chapter_id, operator.user_id, operator)
        if ref is not None:
            # ⚠️ 併發令牌是**章節**的 `VERSION`，而章節**是內容** ⇒ 必須用暫存列那一個。
            # （對照 `reorder_chapters`：那裡的令牌是課程，課程不是內容，故用活表。
            # 判準是「令牌所在的那一列是不是內容」，不是操作本身。）
            nodes = await self._stage_writer.children_of(db, course_id, ENTITY_ITEM, ref.stage_id)
            by_exposed = {exposed_id(source_id=n.source_id, stage_id=n.stage_id): n.stage_id for n in nodes}
            ensure_item_reorder_complete(current_ids=set(by_exposed), requested=req.item_ids)
            rowcount = await self._stage_writer.bump_version(db, ref.stage_id, req.version, operator)
            ensure_version_matched(rowcount=rowcount, entity=_STAGE_ENTITY)
            await self._stage_writer.apply_order(db, [by_exposed[i] for i in req.item_ids], operator)
            await self._log(db, "UPDATE", operator.user_id, course_id, "調整章節項目順序（暫存）")
            return

        chapter = await self._require_owned_chapter(db, chapter_id, operator.user_id)
        current = await self._items.list_by_chapter(db, chapter_id)
        ensure_item_reorder_complete(current_ids={i.item_id for i in current}, requested=req.item_ids)
        rowcount = await self._chapters.bump_version(db, chapter_id, req.version, operator)
        ensure_version_matched(rowcount=rowcount, entity="ET_CHAPTER")
        await self._items.apply_order(db, resequence(req.item_ids), operator)
        await self._log(db, "UPDATE", operator.user_id, chapter.course_id, "調整章節項目順序")

    async def delete_item(self, db: AsyncSession, item_id: int, *, operator: OperatorInfo) -> None:
        """刪除章節項目：本體、其教材 / 測驗內容與學員紀錄皆軟刪，剩餘項目順序遞補。

        已發布 / 已關閉課程只移除**暫存**子樹（#631）——學員紀錄要到「更新」套用時才由
        `stage_apply._DELETERS` 連帶處理，此刻一筆都不動。
        """
        ref, course_id = await self._staged_item(db, item_id, operator.user_id, operator)
        if ref is not None:
            await self._stage_writer.delete_subtree(db, ref.stage_id, operator)
            await self._log(db, "DELETE", operator.user_id, course_id, "刪除章節項目（暫存）")
            return

        item = await self._items.get(db, item_id)
        chapter = await self._require_owned_chapter(db, item.chapter_id, operator.user_id)
        await self._items.soft_delete_with_cascade(db, [item_id], operator)
        await self._items.resequence_remaining(db, item.chapter_id, operator)
        await self._log(db, "DELETE", operator.user_id, chapter.course_id, f"刪除章節項目（{item.item_type}）")

    # ── 能力 ────────────────────────────────────────────────────────────────

    def capabilities(self, roles: frozenset[str]) -> Capabilities:
        """依當前使用者之 ET 角色算出課程相關操作能力。

        純函式（不需 DB）——角色已由 `get_et_context` 查妥並放入 `EtContext`。
        """
        return Capabilities(
            can_create_course=ET_TEACHER in roles,
            can_manage_courses=bool(roles & {ET_TEACHER, ET_ADMIN}),
            # ⚠️ 與上一行的 `ET_TEACHER in roles` **刻意重複**，不要合併成同一個變數：
            # 兩者今天同值，但問的是不同的事（能不能開課 vs 有沒有學員可追蹤），
            # 合併會讓其中一條規則日後改動時靜默拖著另一條走。理由見 `Capabilities`。
            can_track_students=ET_TEACHER in roles,
            can_learn=ET_STUDENT in roles,
        )

    # ── 標籤下拉 ────────────────────────────────────────────────────────────

    async def list_tag_options(self, db: AsyncSession, *, course_id: int | None = None) -> list[TagOption]:
        """受訓對象下拉（單位與職位兩類；啟用中，加上該課程既有配對中的停用標籤）。"""
        return [TagOption.model_validate(t) for t in await self._tags.list_options(db, course_id)]

    # ── 內部 ────────────────────────────────────────────────────────────────

    async def _staged_item(self, db: AsyncSession, item_id: int, actor_id: str, operator):
        """項目 id → 暫存節點；回 `None` 代表該走活表路徑。形狀同 `_staged_chapter`。"""
        ref = await self._stage_writer.resolve_new(db, item_id, ENTITY_ITEM)
        if ref is not None:
            await self._require_owned(db, ref.course_id, actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            return ref, ref.course_id
        item = await self._items.get(db, item_id)
        if item is None:
            raise _ITEM_NOT_FOUND
        chapter = await self._require_owned_chapter(db, item.chapter_id, actor_id)
        course = await self._courses.get(db, chapter.course_id)
        if not is_staged(course):
            return None, chapter.course_id
        await self._stage_writer.lock_course(db, chapter.course_id)
        ref = await self._stage_writer.ref_for_source(
            db, chapter.course_id, ENTITY_ITEM, item_id, operator, gone_error=_ITEM_NOT_FOUND
        )
        return ref, chapter.course_id

    async def _staged_chapter(self, db: AsyncSession, chapter_id: int, actor_id: str, operator):
        """章節 id → 暫存節點；回 `None` 代表該走活表路徑。

        🔴 **負數先解析**：負數必定是「本次編輯新增、活表還沒有」的節點，而正數是活表 id
        ——兩個號碼空間靠正負號隔開（見 `stage_writer.exposed_id`）。

        🔴 **解析完立刻取課程行鎖**，不是等到要寫入才取：呼叫端拿到 `ref` 之後才做
        `append` / `update_payload`，而鎖必須蓋住「解析 → 寫入」整段。理由見
        `stage_writer.lock_course`。

        ⚠️ 鎖排在 `_require_owned` **之後**：先確認是自己的課再排隊，否則任何登入者都能
        用一個不屬於他的 course_id 讓擁有者的編輯卡住。
        """
        ref = await self._stage_writer.resolve_new(db, chapter_id, ENTITY_CHAPTER)
        if ref is not None:
            await self._require_owned(db, ref.course_id, actor_id)
            await self._stage_writer.lock_course(db, ref.course_id)
            return ref, ref.course_id
        chapter = await self._chapters.get(db, chapter_id)
        if chapter is None:
            raise _CHAPTER_NOT_FOUND
        course = await self._require_owned(db, chapter.course_id, actor_id)
        if not is_staged(course):
            return None, chapter.course_id
        await self._stage_writer.lock_course(db, course.course_id)
        ref = await self._stage_writer.ref_for_source(
            db, course.course_id, ENTITY_CHAPTER, chapter_id, operator, gone_error=_CHAPTER_NOT_FOUND
        )
        return ref, chapter.course_id

    async def _require_owned(self, db: AsyncSession, course_id: int, actor_id: str):
        """取課程並確認操作者為擁有者；查無 → 404、非擁有者 → 403。"""
        course = await self._courses.get(db, course_id)
        if course is None:
            raise _NOT_FOUND
        ensure_owner(owner_id=course.owner_id, actor_id=actor_id)
        return course

    async def _require_owned_chapter(self, db: AsyncSession, chapter_id: int, actor_id: str):
        """取章節並確認其所屬課程之擁有者為操作者；查無章節 → 404、非擁有者 → 403。"""
        chapter = await self._chapters.get(db, chapter_id)
        if chapter is None:
            raise _CHAPTER_NOT_FOUND
        await self._require_owned(db, chapter.course_id, actor_id)
        return chapter

    async def _items_by_chapter(self, db: AsyncSession, chapter_ids: list[int]) -> dict[int, list[ItemRow]]:
        """批次取項目並依章節分組（課程詳細頁一次列出所有章節，逐章查會是 N+1）。"""
        grouped: dict[int, list[ItemRow]] = {}
        for item, title, question_count in await self._items.list_rows_by_chapters(db, chapter_ids):
            grouped.setdefault(item.chapter_id, []).append(
                ItemRow(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    title=title,
                    sort_order=item.sort_order,
                    material_id=item.material_id,
                    quiz_id=item.quiz_id,
                    version=item.version,
                    # 非測驗項目的子查詢恆為 0（`quiz_id` 為 NULL、對不到任何題目），
                    # 在此換成 `None`——0 專指「是測驗但沒題目」那個異常狀態。
                    question_count=question_count if item.quiz_id is not None else None,
                )
            )
        return grouped

    async def _ensure_pairs_selectable(self, db: AsyncSession, pairs: set[Pair]) -> None:
        """新掛之配對：單位欄須為**啟用中的單位**、職位欄須為**啟用中的職位**（FR-ET-US3-03 / #538）。

        僅檢核**新增**的配對——課程既有配對中的停用標籤保留、不受影響，若一併檢核會使
        「標籤被停用後該課程再也存不了檔」。

        欄位錯置（單位欄放職位）同樣擋下：那樣的配對在匹配時永遠不成立，靜默存進去只會讓
        教師以為設好了，而沒有任何學員會被帶入。
        """
        if not pairs:
            return
        states = await self._tags.tag_states(db, {tid for pair in pairs for tid in pair if tid is not None})
        for unit_id, role_id in pairs:
            if states.get(unit_id) != (TAG_TYPE_UNIT, True) or states.get(role_id) != (TAG_TYPE_AUDIENCE, True):
                raise AppError(status_code=422, detail="指定之受訓對象無效或未啟用", error_code="ET_COURSE_004")

    async def _log(self, db: AsyncSession, action: str, operator_id: str, course_id: int, description: str) -> None:
        # after_value 只帶 course_name：供 DP05 對象欄顯示課程名而非 ID（#717）。
        # 取**當下**值存進稽核列，課程日後改名不改寫歷史；⛔ 不得加入學員姓名（個資）。
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type=action,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(course_id),
            description=description,
            after_value=await course_audit_payload(db, course_id) or None,
        )


def _pairs_of(req: CourseCreateReq | CourseUpdateReq) -> set[Pair]:
    """請求中的配對 → `{(單位 TAG_ID, 職位 TAG_ID)}`（重複已由 schema 擋下）。"""
    return {(p.unit_tag_id, p.tag_id) for p in req.audiences}
