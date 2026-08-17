"""文件新增與編輯資料存取（US5，寫入 DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG + 送簽前檢核查詢）。

僅 flush 不 commit（交易由 service / middleware 負責）。跨子模組（同屬 DM）直接引用 Model。
指定審核者清單為 `DM_USER_ROLE`（DM 自持）join `DP_USER` 之唯讀查詢。
"""

from collections.abc import Sequence

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.catalog.models import DmTag, DmTagGroup
from app.dm.document.models import DmDocTag, DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dm.roles.authz import DM_REVIEWER
from app.dp.users.models import DpUser

_DRAFT = "DRAFT"
_PENDING = "PENDING"
_OBSOLETE = "OBSOLETE"
_PUBLISHED = "PUBLISHED"
_MANUAL = "MANUAL"


class EditorRepository:
    """文件寫入 + 送簽前檢核查詢。"""

    async def create_document(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        doc_name: str,
        category_code: str,
        func_code: str | None,
        op: OperatorInfo,
    ) -> DmDocument:
        """建立草稿文件（STATUS=DRAFT、CURRENT_VERSION_ID 首版發布前為 null）。"""
        now = utcnow()
        doc = DmDocument(
            doc_id=doc_id,
            doc_name=doc_name,
            category_code=category_code,
            func_code=func_code,
            current_version_id=None,
            status=_DRAFT,
            created_user=op.user_id,
            created_date=now,
        )
        db.add(doc)
        await db.flush()
        return doc

    async def add_version(
        self,
        db: AsyncSession,
        *,
        doc_id: str,
        version_no: str,
        change_summary: str,
        file_name: str,
        file_path: str,
        file_size: int,
        file_mime: str,
        op: OperatorInfo,
    ) -> DmDocVersion:
        """新增一筆草稿版本（STATUS=DRAFT）。"""
        now = utcnow()
        ver = DmDocVersion(
            doc_id=doc_id,
            version_no=version_no,
            change_summary=change_summary,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            file_mime=file_mime,
            status=_DRAFT,
            created_user=op.user_id,
            created_date=now,
        )
        db.add(ver)
        await db.flush()
        return ver

    async def add_tags(self, db: AsyncSession, *, doc_id: str, tag_ids: Sequence[int], op: OperatorInfo) -> None:
        """掛文件標籤（可見對象 + 檢索，去重）。"""
        now = utcnow()
        for tid in dict.fromkeys(tag_ids):  # 去重、保序
            db.add(DmDocTag(doc_id=doc_id, tag_id=tid, created_user=op.user_id, created_date=now))
        await db.flush()

    async def get_document(self, db: AsyncSession, doc_id: str) -> DmDocument | None:
        """取文件主檔（未刪除）。"""
        return await db.scalar(select(DmDocument).where(DmDocument.doc_id == doc_id, DmDocument.deleted == 0))

    async def get_version(self, db: AsyncSession, doc_id: str, version_id: int) -> DmDocVersion | None:
        """取本文件之某版本（未刪除）。"""
        return await db.scalar(
            select(DmDocVersion).where(
                DmDocVersion.version_id == version_id, DmDocVersion.doc_id == doc_id, DmDocVersion.deleted == 0
            )
        )

    async def get_open_draft_version(self, db: AsyncSession, doc_id: str) -> DmDocVersion | None:
        """取該文件既有之未送簽草稿版本（單一草稿規則：Q1=A）；無則 None。"""
        return await db.scalar(
            select(DmDocVersion).where(
                DmDocVersion.doc_id == doc_id, DmDocVersion.status == _DRAFT, DmDocVersion.deleted == 0
            )
        )

    async def version_no_taken(self, db: AsyncSession, doc_id: str, version_no: str) -> bool:
        """同文件內版本號是否已存在（DM-MSG-DM03-009 友善檢核；DB UQ 為並發後盾）。"""
        got = await db.scalar(
            select(DmDocVersion.version_id).where(
                DmDocVersion.doc_id == doc_id, DmDocVersion.version_no == version_no, DmDocVersion.deleted == 0
            )
        )
        return got is not None

    async def has_pending_obsolete(self, db: AsyncSession, doc_id: str) -> bool:
        """該文件是否有進行中（PENDING）之廢止送審（→ 擋上傳新版本 DM-MSG-DM03-004）。"""
        got = await db.scalar(
            select(DmReview.review_id).where(
                DmReview.doc_id == doc_id, DmReview.review_type == _OBSOLETE, DmReview.status == _PENDING
            )
        )
        return got is not None

    async def manual_func_published_elsewhere(self, db: AsyncSession, func_code: str, exclude_doc_id: str) -> bool:
        """同 func_code 是否已有其他「已發布」系統操作手冊（手冊唯一 DM-MSG-DM03-003；DB 部分唯一索引為後盾）。"""
        got = await db.scalar(
            select(DmDocument.doc_id).where(
                DmDocument.func_code == func_code,
                DmDocument.category_code == _MANUAL,
                DmDocument.status == _PUBLISHED,
                DmDocument.doc_id != exclude_doc_id,
                DmDocument.deleted == 0,
            )
        )
        return got is not None

    async def classify_tags(self, db: AsyncSession, tag_ids: Sequence[int]) -> dict[int, str]:
        """回傳 {tag_id: group_type} —— 僅啟用中之標籤（供驗證可見對象 / 檢索標籤有效性）。"""
        if not tag_ids:
            return {}
        rows = await db.execute(
            select(DmTag.tag_id, DmTagGroup.group_type)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmTag.tag_id.in_(list(tag_ids)), DmTag.is_enabled.is_(True))
        )
        return {r.tag_id: r.group_type for r in rows}

    async def category_enabled(self, db: AsyncSession, category_code: str) -> bool:
        """分類是否存在且啟用（受控主檔）。"""
        from app.dm.catalog.models import DmCategory

        got = await db.scalar(
            select(DmCategory.category_code).where(
                DmCategory.category_code == category_code, DmCategory.is_enabled.is_(True)
            )
        )
        return got is not None

    async def func_enabled(self, db: AsyncSession, func_code: str) -> bool:
        """關聯作業項目是否存在且啟用。"""
        from app.dm.catalog.models import DmFunc

        got = await db.scalar(
            select(DmFunc.func_code).where(DmFunc.func_code == func_code, DmFunc.is_enabled.is_(True))
        )
        return got is not None

    async def list_reviewers(self, db: AsyncSession, *, exclude_user_id: str) -> list[Row]:
        """列具 DM_REVIEWER 角色之使用者（join DP_USER 取姓名、排除自己、依姓名排序）。"""
        from app.dm.roles.models import DmUserRole

        stmt = (
            select(DpUser.user_id, DpUser.user_name)
            .join(DmUserRole, DmUserRole.user_id == DpUser.user_id)
            .where(
                DmUserRole.role_code == DM_REVIEWER,
                DmUserRole.deleted == 0,
                DpUser.user_id != exclude_user_id,
                DpUser.deleted == 0,
            )
            .order_by(DpUser.user_name)
        )
        return list((await db.execute(stmt)).all())

    async def get_user_email(self, db: AsyncSession, user_id: str) -> str | None:
        """取使用者 Email（送簽通知收件人）。"""
        return await db.scalar(select(DpUser.email).where(DpUser.user_id == user_id, DpUser.deleted == 0))
