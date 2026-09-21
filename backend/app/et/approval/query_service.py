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

_NAME_REQUIRED = AppError(
    status_code=422,
    detail="請輸入學員姓名",
    error_code="COMMON_001",
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
            AppError: `user_name` 去空白後為空（422 `COMMON_001`）。

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
        paged = await paginate(db, stmt, page, limit, _ApprovalCore)
        rows = await self._enrich(db, paged["data"])
        return {"data": rows, "meta": paged["meta"]}

    async def mine(self, db: AsyncSession, *, actor_id: str, page: int, limit: int) -> PaginatedResult[MyApprovalRow]:
        """學員自查：自己、已通過、未撤銷（`FR-ET-US17-03`）。

        不收 `user_id` 參數——對象恆為 `actor_id`。
        """
        stmt = self._repo.mine_stmt(user_id=actor_id)
        paged = await paginate(db, stmt, page, limit, _ApprovalCore)
        names = await self._repo.course_names(db, [r.course_id for r in paged["data"]])
        rows = [
            MyApprovalRow(
                course_id=r.course_id,
                course_name=names.get(r.course_id, ""),
                approved_at=r.approved_at,
            )
            for r in paged["data"]
        ]
        return {"data": rows, "meta": paged["meta"]}

    async def _enrich(self, db: AsyncSession, core: list[_ApprovalCore]) -> list[ApprovalQueryRow]:
        """補上課程名稱與三個人名（學員 / 核可人 / 撤銷人）。

        三種人名共用同一次 `user_names()` 查詢——它們都指向 `DP_USER`，分三次查只是
        多兩趟往返。
        """
        if not core:
            return []
        course_names = await self._repo.course_names(db, [r.course_id for r in core])
        wanted = {r.user_id for r in core} | {r.approved_by for r in core}
        wanted |= {r.revoked_by for r in core if r.revoked_by}
        people = await self._repo.user_names(db, list(wanted))
        return [
            ApprovalQueryRow(
                user_id=r.user_id,
                user_name=people.get(r.user_id, ""),
                course_id=r.course_id,
                course_name=course_names.get(r.course_id, ""),
                result=r.result,
                result_note=r.result_note,
                approved_at=r.approved_at,
                approved_by_name=people.get(r.approved_by, ""),
                is_revoked=r.is_revoked,
                revoke_reason=r.revoke_reason,
                revoked_by_name=people.get(r.revoked_by) if r.revoked_by else None,
                revoked_at=r.revoked_at,
            )
            for r in core
        ]
