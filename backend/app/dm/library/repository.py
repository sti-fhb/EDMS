"""文件庫搜尋資料存取（US3，唯讀）。

多條件過濾「已發布」目前版本（含廢止待簽核 PENDING_OBSOLETE）、依發布時間 DESC。
`DP_USER`（作者姓名）之 JOIN 為**唯讀查詢例外**（sti-backend-boundaries §報表/查詢：僅 SELECT、
不重實作他模組業務規則）。標籤式可見性判定重用 `dm/document/visibility`（T020a）。
"""

from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import ColumnElement, Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import exists

from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.document.visibility import visible_docs_condition
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

# 文件庫可見狀態集合：PUBLISHED（在架）+ PENDING_OBSOLETE（廢止待簽核，仍對外）。
# 排除 DRAFT / PENDING_REVIEW / OBSOLETE；僅取 CURRENT_VERSION_ID 對應之目前發布版。
_LIBRARY_STATUSES = ("PUBLISHED", "PENDING_OBSOLETE")
_RETRIEVAL = "RETRIEVAL"  # 檢索標籤組（不含 AUDIENCE 權限組）


class LibraryRepository:
    """文件庫查詢（多條件 + 可見性 + 分頁；受控清單下拉）。"""

    def build_conditions(
        self,
        *,
        keyword: str | None,
        category: str | None,
        author: str | None,
        tag_ids: Sequence[int],
        func_code: str | None,
        date_from: date | None,
        date_to: date | None,
        user_id: str,
        roles: Iterable[str],
    ) -> list[ColumnElement[bool]]:
        """組搜尋條件；含**狀態集合**與**標籤式可見性**（兩者獨立 AND，勿混）。"""
        conds: list[ColumnElement[bool]] = [
            DmDocument.deleted == 0,
            DmDocument.status.in_(_LIBRARY_STATUSES),
        ]
        if keyword:
            pattern = f"%{keyword}%"
            conds.append(or_(DmDocument.doc_name.ilike(pattern), DmDocVersion.change_summary.ilike(pattern)))
        if category:
            conds.append(DmDocument.category_code == category)
        if author:
            conds.append(DpUser.user_name.ilike(f"%{author}%"))
        if func_code:
            conds.append(DmDocument.func_code == func_code)
        if date_from:
            conds.append(func.date(DmDocVersion.published_date) >= date_from)
        if date_to:
            conds.append(func.date(DmDocVersion.published_date) <= date_to)
        # 多標籤 AND：每一選定標籤各一 EXISTS（皆須掛）。EXISTS 內 join 標籤組並限 RETRIEVAL，
        # 確保只有「檢索標籤」能作為搜尋條件——即使呼叫端直傳 AUDIENCE（可見對象）之 tag_id 亦不生效（FR-009）。
        for tag_id in tag_ids:
            conds.append(
                exists(
                    select(DmDocTag.doc_tag_id)
                    .select_from(DmDocTag)
                    .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
                    .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
                    .where(
                        DmDocTag.doc_id == DmDocument.doc_id,
                        DmDocTag.tag_id == tag_id,
                        DmDocTag.deleted == 0,
                        DmTagGroup.group_type == _RETRIEVAL,
                    )
                )
            )
        # 標籤式可見性（閱覽者過濾；編輯者/審核者/管理者回 None 不過濾）——與上述條件獨立 AND
        visibility = visible_docs_condition(user_id, roles)
        if visibility is not None:
            conds.append(visibility)
        return conds

    async def count_documents(self, db: AsyncSession, conditions: Sequence[ColumnElement[bool]]) -> int:
        stmt = (
            select(func.count(DmDocument.doc_id))
            .select_from(DmDocument)
            .join(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .outerjoin(DpUser, DmDocument.created_user == DpUser.user_id)
            .where(*conditions)
        )
        return await db.scalar(stmt) or 0

    async def list_documents(
        self, db: AsyncSession, conditions: Sequence[ColumnElement[bool]], *, offset: int, limit: int
    ) -> list[Row]:
        """回目前發布版之 enriched 列（含作者姓名 / 分類名 / func 名 / 發布時間），依發布時間 DESC。"""
        stmt = (
            select(
                DmDocument.doc_id,
                DmDocument.doc_name,
                DmDocument.category_code,
                DmCategory.category_name,
                DmDocument.func_code,
                DmFunc.func_name,
                DmDocument.created_user,
                DpUser.user_name,
                DmDocVersion.published_date,
            )
            .select_from(DmDocument)
            .join(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .join(DmCategory, DmDocument.category_code == DmCategory.category_code)
            .outerjoin(DmFunc, DmDocument.func_code == DmFunc.func_code)
            .outerjoin(DpUser, DmDocument.created_user == DpUser.user_id)
            .where(*conditions)
            .order_by(DmDocVersion.published_date.desc(), DmDocument.doc_id)
            .offset(offset)
            .limit(limit)
        )
        return list((await db.execute(stmt)).all())

    async def fetch_retrieval_tags(self, db: AsyncSession, doc_ids: Sequence[str]) -> dict[str, list[str]]:
        """批次取各文件之**檢索標籤**名稱（不含 AUDIENCE 權限標籤）；供清單灰字頓號呈現。

        **不濾 is_enabled**：此為「既有文件已掛標記」之顯示，標籤停用後既有引用 100% 保留
        （spec_us1 FR-001 / DM-MSG-DM09-003：停用僅影響後續新增/搜尋下拉，不動既有標記）。
        """
        if not doc_ids:
            return {}
        stmt = (
            select(DmDocTag.doc_id, DmTag.tag_name)
            .select_from(DmDocTag)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(
                DmDocTag.doc_id.in_(doc_ids),
                DmDocTag.deleted == 0,
                DmTagGroup.group_type == _RETRIEVAL,
            )
            .order_by(DmDocTag.doc_id, DmTag.tag_id)
        )
        result: dict[str, list[str]] = {}
        for doc_id, tag_name in (await db.execute(stmt)).all():
            result.setdefault(doc_id, []).append(tag_name)
        return result

    async def list_func_options(self, db: AsyncSession) -> list[Row]:
        """啟用中 func_name 清單（系統操作手冊檢索下拉）。"""
        stmt = select(DmFunc.func_code, DmFunc.func_name).where(DmFunc.is_enabled.is_(True)).order_by(DmFunc.func_code)
        return list((await db.execute(stmt)).all())

    async def list_retrieval_tags(self, db: AsyncSession) -> list[Row]:
        """啟用中檢索標籤清單（含所屬組代碼供前端分組）；**排除 AUDIENCE 權限組**。"""
        stmt = (
            select(DmTag.tag_id, DmTag.tag_name, DmTagGroup.tag_group_code)
            .select_from(DmTag)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmTagGroup.group_type == _RETRIEVAL, DmTag.is_enabled.is_(True))
            .order_by(DmTagGroup.tag_group_code, DmTag.tag_id)
        )
        return list((await db.execute(stmt)).all())
