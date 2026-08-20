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
_PENDING_REVIEW = "PENDING_REVIEW"
_PENDING = "PENDING"
_OBSOLETE = "OBSOLETE"
_PUBLISHED = "PUBLISHED"
_MANUAL = "MANUAL"
_AUDIENCE = "AUDIENCE"
_RETRIEVAL = "RETRIEVAL"


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
        file_name: str | None,
        file_path: str | None,
        file_size: int | None,
        file_mime: str | None,
        op: OperatorInfo,
    ) -> DmDocVersion:
        """新增一筆草稿版本（STATUS=DRAFT）；檔案可暫無（存草稿不卡，送簽時才必備）。"""
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

    async def set_tags(self, db: AsyncSession, *, doc_id: str, tag_ids: Sequence[int], op: OperatorInfo) -> None:
        """設定文件標籤為指定集合（可見對象 + 檢索）——差異式覆寫。

        標籤為**文件層**（DM_DOC_TAG 無 version_id），編輯新版本改標籤即改此。採軟刪除復用避開
        UQ(DOC_ID, TAG_ID)：目標集內既有列復活（deleted=0）/ 新列插入、目標集外之有效列軟刪除。
        新增文件（無既有列）時等同全插入。
        """
        now = utcnow()
        wanted = list(dict.fromkeys(tag_ids))  # 去重、保序
        wanted_set = set(wanted)
        existing = {
            row.tag_id: row for row in (await db.scalars(select(DmDocTag).where(DmDocTag.doc_id == doc_id))).all()
        }
        for tid in wanted:
            row = existing.get(tid)
            if row is None:
                db.add(DmDocTag(doc_id=doc_id, tag_id=tid, created_user=op.user_id, created_date=now))
            elif row.deleted != 0:
                row.deleted = 0
                row.updated_user, row.updated_date = op.user_id, now
        for tid, row in existing.items():
            if tid not in wanted_set and row.deleted == 0:
                row.deleted = 1
                row.updated_user, row.updated_date = op.user_id, now
        await db.flush()

    async def has_audience_tag(self, db: AsyncSession, doc_id: str) -> bool:
        """該文件是否至少掛 1 個有效之可見對象（AUDIENCE 組）標籤（送簽檢核 DM_DOC_005）。"""
        got = await db.scalar(
            select(DmDocTag.doc_tag_id)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0, DmTagGroup.group_type == _AUDIENCE)
        )
        return got is not None

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

    async def get_author_open_version(self, db: AsyncSession, doc_id: str, user_id: str) -> DmDocVersion | None:
        """取「該撰寫者」於此文件既有之進行中版本（草稿或審核中）；無則 None。

        每人每文件至多一份進行中版本：草稿（DRAFT）或已送審核中（PENDING_REVIEW）。同時擋審核中，
        杜絕「送審後又另開草稿」使退回無法一致轉回草稿（會撞每人一份草稿唯一索引）之邊界。
        放寬自原「單一草稿」：不同撰寫者可各自對同一文件開新版本、互不阻擋（避免有人留稿或請假時卡住
        全部人）；同文件至多一筆進行中送審另由 DM_REVIEW_002 把關。回傳版本供呼叫端依 status 給對應訊息。
        """
        return await db.scalar(
            select(DmDocVersion).where(
                DmDocVersion.doc_id == doc_id,
                DmDocVersion.created_user == user_id,
                DmDocVersion.status.in_((_DRAFT, _PENDING_REVIEW)),
                DmDocVersion.deleted == 0,
            )
        )

    async def get_doc_tags(self, db: AsyncSession, doc_id: str) -> dict[str, list[str]]:
        """取文件現有有效標籤，依組型分為可見對象 / 檢索（TAG_ID 字串），供編輯模式預帶。"""
        rows = await db.execute(
            select(DmTag.tag_id, DmTagGroup.group_type)
            .select_from(DmDocTag)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmDocTag.doc_id == doc_id, DmDocTag.deleted == 0)
            .order_by(DmTag.tag_id)
        )
        audience: list[str] = []
        retrieval: list[str] = []
        for tag_id, group_type in rows.all():
            (audience if group_type == _AUDIENCE else retrieval).append(str(tag_id))
        return {"audience_ids": audience, "retrieval_ids": retrieval}

    async def version_no_taken(self, db: AsyncSession, doc_id: str, version_no: str) -> bool:
        """版本號是否已被本文件之「已發布」版本使用（PUBLISHED / SUPERSEDED）。

        僅卡與已發布版本重複——草稿 / 送審中 / 退回不計，故多人可各自草稿填同版號；送簽時據此檢核
        （DM-MSG-DM03-009）。DB partial unique index（UX_DM_DOC_VERSION_RELEASED_NO）為並發後盾。
        """
        got = await db.scalar(
            select(DmDocVersion.version_id).where(
                DmDocVersion.doc_id == doc_id,
                DmDocVersion.version_no == version_no,
                DmDocVersion.status.in_(("PUBLISHED", "SUPERSEDED")),
                DmDocVersion.deleted == 0,
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

    async def get_user_name_email(self, db: AsyncSession, user_id: str) -> Row | None:
        """取使用者姓名 + Email（送簽通知收件人與範本變數）；查無 None。"""
        return (
            await db.execute(
                select(DpUser.user_name, DpUser.email).where(DpUser.user_id == user_id, DpUser.deleted == 0)
            )
        ).first()

    # ── 表單受控下拉（啟用中）─────────────────────────────

    async def list_categories(self, db: AsyncSession) -> list[Row]:
        """分類下拉（啟用中，依碼排序）。"""
        from app.dm.catalog.models import DmCategory

        stmt = (
            select(DmCategory.category_code, DmCategory.category_name)
            .where(DmCategory.is_enabled.is_(True))
            .order_by(DmCategory.category_code)
        )
        return list((await db.execute(stmt)).all())

    async def list_funcs(self, db: AsyncSession) -> list[Row]:
        """關聯作業項目下拉（啟用中，依碼排序）。"""
        from app.dm.catalog.models import DmFunc

        stmt = select(DmFunc.func_code, DmFunc.func_name).where(DmFunc.is_enabled.is_(True)).order_by(DmFunc.func_code)
        return list((await db.execute(stmt)).all())

    async def list_audience_tags(self, db: AsyncSession) -> list[Row]:
        """可見對象下拉（AUDIENCE 組、啟用中；**含通用值「全體」**，文件掛上即所有閱覽者可見）。"""
        stmt = (
            select(DmTag.tag_id, DmTag.tag_name)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmTagGroup.group_type == _AUDIENCE, DmTag.is_enabled.is_(True))
            .order_by(DmTag.tag_id)
        )
        return list((await db.execute(stmt)).all())

    async def list_retrieval_tags(self, db: AsyncSession) -> list[Row]:
        """檢索標籤下拉（RETRIEVAL 型、啟用中，含所屬組供分組）。"""
        stmt = (
            select(DmTag.tag_id, DmTag.tag_name, DmTag.tag_group_code)
            .join(DmTagGroup, DmTag.tag_group_code == DmTagGroup.tag_group_code)
            .where(DmTagGroup.group_type == _RETRIEVAL, DmTag.is_enabled.is_(True))
            .order_by(DmTag.tag_group_code, DmTag.tag_id)
        )
        return list((await db.execute(stmt)).all())
