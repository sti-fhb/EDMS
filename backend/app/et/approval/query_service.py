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
- **Q2 = A**：`user_name` 必填，去空白後為空視為未填
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.pagination import PaginatedResult, paginate
from app.et.approval.query_repository import EtApprovalQueryRepository
from app.et.approval.query_rules import visible_clause
from app.et.approval.schemas import ApprovalQueryRow, MyApprovalRow, _ApprovalCore
from app.et.roles.authz import is_admin

#: 姓名必填（SA Q2 裁示 A）。
#:
#: ⚠️ **不共用 `COMMON_001`**（未提供任何更新欄位）：`docs/ref/error-codes.md` 的對照表是
#: code → message 的 1:1 映射，而本情境的訊息是「請輸入學員姓名」。同一個代碼掛兩種訊息
#: 會讓依該表建對照（例如前端 i18n）的人拿到與畫面不符的字串。
_NAME_REQUIRED = AppError(
    status_code=422,
    detail="請輸入學員姓名",
    error_code="ET_APPROVAL_006",
)


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
        user_name: str,
        result: str | None,
        page: int,
        limit: int,
    ) -> PaginatedResult[ApprovalQueryRow]:
        """教師 / 管理者依學員姓名查詢核可紀錄。

        Raises:
            AppError: `user_name` 去空白後為空（422 `ET_APPROVAL_006`）。

        ⚠️ 姓名必填是 SA Q2 裁示 A 的落地。理由不是安全潔癖，而是**留白查全部沒有對應
        需求**（客戶要的是「用姓名查」），而它會回傳 `user_id` 與姓名對照——等於提供一份
        有受訓紀錄的員工名冊。日後若需要「班級核可總表」，那屬 ET03 的範疇（以課程為
        單位），不由本查詢承接。
        """
        keyword = user_name.strip()
        if not keyword:
            raise _NAME_REQUIRED

        stmt = self._repo.teacher_query_stmt(
            user_name=keyword,
            visible=visible_clause(actor_id=actor_id, is_admin=is_admin(roles)),
            result=result,
        )
        admin = is_admin(roles)
        paged = await paginate(db, stmt, page, limit, _ApprovalCore)
        rows = await self._enrich(db, paged["data"], actor_id=actor_id, is_admin=admin)
        return {"data": rows, "meta": paged["meta"]}

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
