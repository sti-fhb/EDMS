"""文件詳細頁資料存取（US4，唯讀 + 下載記錄）。

存取控制套 `visible_docs_condition`（閱覽者不可取未授權可見對象之文件）。作者 / 核准者姓名經唯讀
join `DP_USER`（sti-backend-boundaries §報表/查詢例外）。下載目前發布版寫 `DM_DOC_READ`（唯一約束去重）。
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.document.visibility import visible_docs_condition
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

_RETRIEVAL = "RETRIEVAL"
_PENDING = "PENDING"
_OBSOLETE = "OBSOLETE"


class DetailRepository:
    """文件詳細 / 版本 / 送審狀態 / 廢止資訊 / 檔案 / 閱讀紀錄。"""

    def _access_conditions(self, doc_id: str, user_id: str, roles: Iterable[str]) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = [DmDocument.doc_id == doc_id, DmDocument.deleted == 0]
        visibility = visible_docs_condition(user_id, roles)  # 閱覽者過濾；其餘 None
        if visibility is not None:
            conds.append(visibility)
        return conds

    async def get_document(self, db: AsyncSession, doc_id: str, user_id: str, roles: Iterable[str]) -> Row | None:
        """目前發布版之詳細（含作者 / 核准者姓名 / 分類 / func / 檔案 meta）；套存取控制、查無回 None。"""
        author = aliased(DpUser)
        approver = aliased(DpUser)
        stmt = (
            select(
                DmDocument.doc_id,
                DmDocument.doc_name,
                DmDocument.status,
                DmDocument.category_code,
                DmDocument.func_code,
                DmDocument.created_user.label("author_id"),
                DmCategory.category_name,
                DmFunc.func_name,
                DmDocVersion.version_id,
                DmDocVersion.version_no,
                DmDocVersion.published_date,
                DmDocVersion.file_name,
                DmDocVersion.file_mime,
                DmDocVersion.file_size,
                DmDocVersion.created_date.label("version_created"),
                DmDocVersion.approver_user_id.label("approver_id"),
                author.user_name.label("author_name"),
                approver.user_name.label("approver_name"),
            )
            .select_from(DmDocument)
            .outerjoin(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .join(DmCategory, DmDocument.category_code == DmCategory.category_code)
            .outerjoin(DmFunc, DmDocument.func_code == DmFunc.func_code)
            .outerjoin(author, DmDocument.created_user == author.user_id)
            .outerjoin(approver, DmDocVersion.approver_user_id == approver.user_id)
            .where(*self._access_conditions(doc_id, user_id, roles))
        )
        return (await db.execute(stmt)).first()

    async def get_retrieval_tags(self, db: AsyncSession, doc_id: str) -> list[str]:
        """文件之檢索標籤名稱（資訊面板；不含 AUDIENCE、不濾 is_enabled 以保留既有標記）。"""
        stmt = (
            select(DmTag.tag_name)
            .select_from(DmDocTag)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0, DmTagGroup.group_type == _RETRIEVAL)
            .order_by(DmTag.tag_id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_versions(self, db: AsyncSession, doc_id: str) -> list[Row]:
        """該文件所有版本（發布時間 DESC；含撰寫者 / 核准者姓名）。"""
        author = aliased(DpUser)
        approver = aliased(DpUser)
        stmt = (
            select(
                DmDocVersion.version_id,
                DmDocVersion.version_no,
                DmDocVersion.change_summary,
                DmDocVersion.published_date,
                DmDocVersion.file_mime,
                DmDocVersion.created_user.label("author_id"),
                author.user_name.label("author_name"),
                approver.user_name.label("approver_name"),
            )
            .select_from(DmDocVersion)
            .outerjoin(author, DmDocVersion.created_user == author.user_id)
            .outerjoin(approver, DmDocVersion.approver_user_id == approver.user_id)
            .where(DmDocVersion.doc_id == doc_id, DmDocVersion.deleted == 0)
            .order_by(DmDocVersion.published_date.desc().nullslast(), DmDocVersion.version_id.desc())
        )
        return list((await db.execute(stmt)).all())

    async def has_pending_review(self, db: AsyncSession, doc_id: str) -> bool:
        """該文件是否有進行中（PENDING）之送審週期（決定編輯 / 廢止入口是否失效）。"""
        stmt = select(DmReview.review_id).where(DmReview.doc_id == doc_id, DmReview.status == _PENDING).limit(1)
        return (await db.scalar(stmt)) is not None

    async def get_obsolete_review(self, db: AsyncSession, doc_id: str) -> Row | None:
        """已核准之廢止送審週期（供 read-only 廢止 banner）；無則 None。"""
        applicant = aliased(DpUser)
        approver = aliased(DpUser)
        stmt = (
            select(
                DmReview.created_user.label("applicant_id"),
                DmReview.complete_date,
                DmReview.reason,
                DmReview.obsolete_file_name,
                applicant.user_name.label("applicant_name"),
                approver.user_name.label("approver_name"),
            )
            .select_from(DmReview)
            .outerjoin(applicant, DmReview.created_user == applicant.user_id)
            .outerjoin(approver, DmReview.approver_user_id == approver.user_id)
            .where(DmReview.doc_id == doc_id, DmReview.review_type == _OBSOLETE, DmReview.status == "APPROVED")
            .order_by(DmReview.complete_date.desc().nullslast())
            .limit(1)
        )
        return (await db.execute(stmt)).first()

    async def get_document_meta(self, db: AsyncSession, doc_id: str, user_id: str, roles: Iterable[str]) -> Row | None:
        """取文件之 current_version_id + status（套存取控制），供檔案端點判斷目前版 / 存取權。"""
        stmt = select(DmDocument.current_version_id, DmDocument.status).where(
            *self._access_conditions(doc_id, user_id, roles)
        )
        return (await db.execute(stmt)).first()

    async def get_version_file(self, db: AsyncSession, doc_id: str, version_id: int) -> Row | None:
        """取某版本之檔案 metadata（file_path / mime / name）；限本文件、未刪除。"""
        stmt = select(DmDocVersion.file_path, DmDocVersion.file_mime, DmDocVersion.file_name).where(
            DmDocVersion.version_id == version_id, DmDocVersion.doc_id == doc_id, DmDocVersion.deleted == 0
        )
        return (await db.execute(stmt)).first()

    async def write_read(self, db: AsyncSession, *, doc_id: str, version_id: int, user_id: str) -> None:
        """寫一筆下載閱讀紀錄；唯一約束 (DOC,VERSION,USER) 天然去重（重複下載 no-op）。"""
        stmt = (
            pg_insert(DmDocRead)
            .values(doc_id=doc_id, version_id=version_id, created_user=user_id, created_date=utcnow())
            .on_conflict_do_nothing(constraint="UQ_DM_DOC_READ_DOC_VER_USER")
        )
        await db.execute(stmt)
