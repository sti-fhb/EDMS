"""核可查詢 Service（US17 / #385）——**唯讀，不寫任何東西**。

## 兩支端點刻意分開，而不是同一支加參數

`GET /approvals`（教師 / 管理者）與 `GET /approvals/mine`（學員）的授權模型、回應欄位
與資料範圍三者都不同。合併成一支之後，「學員誤拿到教師欄位」就只差一個判斷式——而那
個判斷式改壞了不會有任何東西變紅（回應多幾個欄位，前端照樣渲染）。

分開的附帶好處：`/mine` **不收任何 `user_id` 參數**，對象一律取自 token。
`FR-ET-US17-04`「學員竄改參數查他人」因此在介面上就沒有可竄改的參數，而不是靠一道
判斷式擋下。

## SA 裁示（2026-09-21）

- **Q1 = C**：教師（非管理者）依結果分流，見 `query_rules.visible_clause`
- **Q2 = A**：`keyword` 必填，去空白後為空視為未填（#436 起可為姓名或 Email）
  ——⚠️ **已於 #439 換手段**：改為「關鍵字與課程至少給一個」，並新增
  「非管理者只能依自己開設的課程篩選」。裁示 A 擋的**目的**（不可傾印員工名冊）
  未被放寬，見 `query_rules.normalize_search_criteria`。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResult, paginate
from app.et.approval.query_repository import EtApprovalQueryRepository
from app.et.approval.query_rules import (
    ensure_course_filter_allowed,
    normalize_search_criteria,
    visible_clause,
)
from app.et.approval.schemas import (
    ApprovalCourseOption,
    ApprovalQueryRow,
    MyApprovalRow,
    _ApprovalCore,
)
from app.et.roles.authz import is_admin


class EtApprovalQueryService:
    """核可紀錄查詢——教師 / 管理者依姓名查，學員查自己已通過。"""

    def __init__(self, repository: EtApprovalQueryRepository | None = None) -> None:
        self._repo = repository or EtApprovalQueryRepository()

    async def search(
        self,
        db: AsyncSession,
        *,
        actor_id: str,
        roles: frozenset[str],
        keyword: str | None,
        course_id: int | None,
        result: str | None,
        page: int,
        limit: int,
    ) -> PaginatedResult[ApprovalQueryRow]:
        """教師 / 管理者依學員姓名 / Email 與 / 或課程查詢核可紀錄。

        Raises:
            AppError: 關鍵字與課程皆未提供（422 `ET_APPROVAL_006`）；
                非管理者以他人課程篩選（403 `ET_APPROVAL_007`）。

        ## 條件「至少給一個」取代了原本的「姓名必填」（#439）

        SA Q2 裁示 A 的兩半理由現在各有歸宿：「沒有對應需求」已被 #439 推翻（使用者常常
        正是不知道有誰可以查），「會傾印員工名冊」則**在課程路徑上**由兩道閘一起承接
        ——兩者皆不給仍回 422，而課程篩選對非管理者限縮在自己開設的課。少掉任何一道，
        本方法就等於開放留白查詢，完整理由見 `query_rules` 的兩個函式。

        ⛔ **關鍵字路徑不在那個保護範圍內**：`keyword="@"` 對全體使用者命中（`EMAIL`
        為 `NOT NULL`、`@` 非 LIKE 萬用字元故不被跳脫）。#436 引入、追蹤於 #456。
        防列舉真正靠的是母體限制與角色受控，見 `router` 模組 docstring。

        ⚠️ 擁有權閘**只在有給 `course_id` 時**才查課程——沒給時多那一次往返沒有意義，
        而且 `courses([])` 會回空 dict，`brief` 恆為 `None`，教師側會被 fail-closed
        擋成 403。那是一條只在「以關鍵字查詢」時才踩得到的假 403。
        """
        admin = is_admin(roles)
        keyword = normalize_search_criteria(keyword=keyword, course_id=course_id)
        if course_id is not None:
            courses = await self._repo.courses(db, [course_id])
            brief = courses.get(course_id)
            ensure_course_filter_allowed(
                owner_id=brief.owner_id if brief is not None else None,
                actor_id=actor_id,
                is_admin=admin,
            )

        stmt = self._repo.teacher_query_stmt(
            keyword=keyword,
            visible=visible_clause(actor_id=actor_id, is_admin=admin),
            course_id=course_id,
            result=result,
        )
        paged = await paginate(db, stmt, page, limit, _ApprovalCore)
        rows = await self._enrich(db, paged["data"], actor_id=actor_id, is_admin=admin)
        return {"data": rows, "meta": paged["meta"]}

    async def filter_courses(
        self, db: AsyncSession, *, actor_id: str, roles: frozenset[str]
    ) -> list[ApprovalCourseOption]:
        """ET10 課程下拉的選項——**有核可紀錄的**課程（#439）。

        教師只列自己開設的課，管理者不限。`ApprovalCourseOption` 的 docstring 說明為何
        母體是核可紀錄而不是課程清單。

        ⚠️ 回傳空清單有兩種成因（「沒開過課」與「開的課還沒有人被核可」），本方法
        **不區分**——兩者的下一步相同（去 ET03 核可學員），而要分得出來得多一次查詢。
        前端據此顯示單一句說明，見 `TeacherApprovalQuery`。
        """
        owner_id = None if is_admin(roles) else actor_id
        rows = await self._repo.filter_course_options(db, owner_id=owner_id)
        return [ApprovalCourseOption(course_id=cid, course_name=name) for cid, name in rows]

    async def mine(self, db: AsyncSession, *, actor_id: str, page: int, limit: int) -> PaginatedResult[MyApprovalRow]:
        """學員自查：自己、已通過、未撤銷（`FR-ET-US17-03`）。

        不收 `user_id` 參數——對象恆為 `actor_id`。
        """
        stmt = self._repo.mine_stmt(user_id=actor_id)
        paged = await paginate(db, stmt, page, limit, _ApprovalCore)
        courses = await self._repo.courses(db, [r.course_id for r in paged["data"]])
        rows = [
            MyApprovalRow(
                course_id=r.course_id,
                course_name=courses[r.course_id].name if r.course_id in courses else "",
                approved_at=r.approved_at,
            )
            for r in paged["data"]
        ]
        return {"data": rows, "meta": paged["meta"]}

    async def _enrich(
        self, db: AsyncSession, core: list[_ApprovalCore], *, actor_id: str, is_admin: bool
    ) -> list[ApprovalQueryRow]:
        """補上課程名稱與三個人名（學員 / 核可人 / 撤銷人），並遮蔽他人課程的考核評語。

        三種人名共用同一次 `user_names()` 查詢——它們都指向 `DP_USER`，分三次查只是
        多兩趟往返。

        ## 🔴 `RESULT_NOTE` 只對該課程 owner 與管理者顯示（SA 裁示 2026-09-21）

        裁示 C 原本只切了**結果**維度（不通過 / 已撤銷限自己 owner），沒切**欄位**維度。
        但 `ApproveReq.result_note` 明文允許 `PASS` 附備註（上限 1000 字），於是：

        > 教師甲在自己的課給某人 PASS，備註寫「第二次補考才通過，單採操作仍不穩」。
        > 教師乙（與該課程、該學員毫無關係）查該學員 → 完整讀到那段評語。

        裁示 C 的理由自己寫著「不通過與其 `RESULT_NOTE` 是考核評價，不該讓同儕教師隨意
        翻閱」——負面評語只要掛在 PASS 上就整份流出去。這與 `query_rules` 防的「撤銷原因
        從側門漏出」是同一類側門的另一半。

        ⚠️ 遮蔽在**後端**，回傳 `None` 而非交給前端不渲染。
        """
        if not core:
            return []
        courses = await self._repo.courses(db, [r.course_id for r in core])
        wanted = {r.user_id for r in core} | {r.approved_by for r in core}
        wanted |= {r.revoked_by for r in core if r.revoked_by}
        people = await self._repo.user_names(db, list(wanted))

        def note_of(row: _ApprovalCore) -> str | None:
            """他人課程的考核評語一律不回傳。查無課程時 fail-closed（遮蔽）。"""
            if is_admin:
                return row.result_note
            course = courses.get(row.course_id)
            return row.result_note if course is not None and course.owner_id == actor_id else None

        return [
            ApprovalQueryRow(
                user_id=r.user_id,
                user_name=people.get(r.user_id, ""),
                course_id=r.course_id,
                course_name=courses[r.course_id].name if r.course_id in courses else "",
                result=r.result,
                result_note=note_of(r),
                approved_at=r.approved_at,
                approved_by_name=people.get(r.approved_by, ""),
                is_revoked=r.is_revoked,
                revoke_reason=r.revoke_reason,
                revoked_by_name=people.get(r.revoked_by) if r.revoked_by else None,
                revoked_at=r.revoked_at,
            )
            for r in core
        ]
