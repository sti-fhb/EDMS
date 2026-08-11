"""文件庫與檢索服務（US3，唯讀）。

多條件搜尋已發布目前版本（含廢止待簽核）、依發布時間 DESC 手動分頁（enriched 列，仿 dp-audit）。
標籤式可見性由 repository 併入條件（閱覽者過濾、其餘不過濾）；作者姓名經唯讀 join DP_USER 取得。
"""

from app.core.pagination import PaginatedResult
from app.dm.deps import DmContext
from app.dm.library.repository import LibraryRepository
from app.dm.library.schemas import Capabilities, ControlledOption, DocumentListItem, DocumentQuery
from app.dm.roles.authz import DM_EDITOR


class LibraryService:
    """文件庫查詢（搜尋 / 受控清單下拉）。"""

    def __init__(self, repository: LibraryRepository | None = None) -> None:
        self._repo = repository or LibraryRepository()

    async def search(
        self, db, *, query: DocumentQuery, ctx: DmContext, page: int, limit: int
    ) -> PaginatedResult[DocumentListItem]:
        """多條件搜尋 → 已發布目前版本清單（後端分頁、發布時間 DESC）。"""
        conditions = self._repo.build_conditions(
            keyword=query.keyword,
            category=query.category,
            author=query.author,
            tag_ids=query.tag_ids,
            func_code=query.func_code,
            date_from=query.date_from,
            date_to=query.date_to,
            user_id=ctx.user_id,
            roles=ctx.roles,
        )
        total = await self._repo.count_documents(db, conditions)
        total_pages = (total + limit - 1) // limit if total > 0 else 0

        if total == 0 or page > total_pages:
            return {"data": [], "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

        rows = await self._repo.list_documents(db, conditions, offset=(page - 1) * limit, limit=limit)
        tags_by_doc = await self._repo.fetch_retrieval_tags(db, [r.doc_id for r in rows])
        data = [
            DocumentListItem(
                doc_id=r.doc_id,
                doc_name=r.doc_name,
                category_code=r.category_code,
                category_name=r.category_name,
                published_date=r.published_date,
                author_id=r.created_user,
                author_name=r.user_name,
                func_code=r.func_code,
                func_name=r.func_name,
                tags=tags_by_doc.get(r.doc_id, []),
            )
            for r in rows
        ]
        return {"data": data, "meta": {"total": total, "page": page, "limit": limit, "total_pages": total_pages}}

    async def list_func_options(self, db) -> list[ControlledOption]:
        """系統操作手冊檢索用之 func_name 下拉（啟用中）。"""
        rows = await self._repo.list_func_options(db)
        return [ControlledOption(code=r.func_code, name=r.func_name) for r in rows]

    async def list_retrieval_tags(self, db) -> list[ControlledOption]:
        """檢索標籤下拉（啟用中，含所屬組供分組）；不含可見對象/權限標籤。"""
        rows = await self._repo.list_retrieval_tags(db)
        return [ControlledOption(code=str(r.tag_id), name=r.tag_name, group_code=r.tag_group_code) for r in rows]

    def capabilities(self, ctx: DmContext) -> Capabilities:
        """當前使用者文件庫操作能力：具編輯者角色才可新增文件（FR-006 / AC8）。"""
        return Capabilities(can_create=DM_EDITOR in ctx.roles)
