"""個人專區（US9）資料存取：草稿匣（三類）+ 我的文件動態（衍生查詢，無新表）。"""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmReview
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，同 dm/review、dm/detail）

_DRAFT = "DRAFT"
_OBSOLETE = "OBSOLETE"
_PENDING = "PENDING"
_APPROVED = "APPROVED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
_HIDDEN_PARENT_STATUSES = (_OBSOLETE, _PENDING_OBSOLETE)  # 廢止待簽核 / 已廢止之文件其孤兒草稿不列草稿匣


class PersonalRepository:
    """草稿匣 / 我的文件動態查詢。"""

    async def list_user_drafts(self, db: AsyncSession, user_id: str) -> list[Row]:
        """該使用者之 DRAFT 版本 + 該版本最近一次送審狀態（供三類分類）。

        DRAFT 版本只會是：從未送審 / 被退回回草稿（REJECTED）/ 已撤回回草稿（WITHDRAWN）——
        PENDING 中之版本為 PENDING_REVIEW、不在此列。以相關子查詢取最近一次 DM_REVIEW.status。
        """
        # tie-break review_id：同版本兩筆 review 之 submit_date 相同時（快速連續 utcnow）取用穩定
        latest_status = (
            select(DmReview.status)
            .where(DmReview.version_id == DmDocVersion.version_id)
            .order_by(DmReview.submit_date.desc(), DmReview.review_id.desc())
            .limit(1)
            .correlate(DmDocVersion)
            .scalar_subquery()
        )
        stmt = (
            select(
                DmDocVersion.version_id,
                DmDocVersion.doc_id,
                DmDocVersion.version_no,
                DmDocVersion.change_summary,
                DmDocVersion.updated_date,
                DmDocument.doc_name,
                DmDocument.category_code,
                latest_status.label("latest_review_status"),
            )
            .join(DmDocument, (DmDocVersion.doc_id == DmDocument.doc_id) & (DmDocument.deleted == 0))
            .where(
                DmDocVersion.created_user == user_id,
                DmDocVersion.status == _DRAFT,
                DmDocVersion.deleted == 0,
                # 已廢止 / 廢止待簽核之文件其孤兒草稿不顯示（#1；不主動刪、資料保留；廢止若被退回、
                # 文件回 PUBLISHED，草稿即重新出現）。廢止過程改於「文件廢止通知」呈現含發起人。
                DmDocument.status.notin_(_HIDDEN_PARENT_STATUSES),
            )
            # 排序鍵以「最後異動」為準，未編輯過（updated_date NULL）之新草稿退回 created_date，避免排最後
            .order_by(
                func.coalesce(DmDocVersion.updated_date, DmDocVersion.created_date).desc(),
                DmDocVersion.version_id.desc(),
            )
        )
        return list((await db.execute(stmt)).all())

    async def get_version(self, db: AsyncSession, version_id: int, *, for_update: bool = False) -> DmDocVersion | None:
        """取未刪除版本（草稿刪除授權 / 狀態檢核用）；for_update=True 時上鎖（刪除路徑防 TOCTOU）。"""
        stmt = select(DmDocVersion).where(DmDocVersion.version_id == version_id, DmDocVersion.deleted == 0)
        if for_update:
            stmt = stmt.with_for_update()
        return await db.scalar(stmt)

    def _activity_select(self, *, party_col: InstrumentedAttribute[str]) -> Select[Any]:
        """組 activity 基礎查詢：送審週期各欄 + 對造人姓名（party_col 對應之 DP_USER.USER_NAME）。

        最終呈現順序由 service 依展開後之事件時間重排（見 PersonalService._build_events），此處不加 order_by。
        """
        party_user = aliased(DpUser)
        return (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.review_type,
                DmReview.status,
                DmReview.submit_date,
                DmReview.complete_date,
                DmDocument.doc_name,
                party_user.user_name.label("party_name"),
            )
            .join(DmDocument, (DmReview.doc_id == DmDocument.doc_id) & (DmDocument.deleted == 0))
            .outerjoin(party_user, party_col == party_user.user_id)
        )

    async def list_author_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """撰寫者視角近 30 天狀態變動事件——僅本人送出之送審（created_user＝我；含本人自行發起之廢止）。

        本人「未發起」但被他人廢止之文件不混入此處（避免看起來像自己發起廢止），改於獨立之
        「文件廢止通知」呈現並標明發起人（見 list_obsolete_notices）。對造人 party_name＝指定審核者姓名。
        """
        stmt = self._activity_select(party_col=DmReview.assigned_reviewer).where(
            DmReview.created_user == user_id,
            or_(DmReview.submit_date >= since, DmReview.complete_date >= since),
        )
        return list((await db.execute(stmt)).all())

    async def list_reviewer_activity(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """審核者視角近 30 天狀態變動事件（assigned_reviewer＝我）；對造人 party_name＝送審者姓名。"""
        stmt = self._activity_select(party_col=DmReview.created_user).where(
            DmReview.assigned_reviewer == user_id,
            or_(DmReview.submit_date >= since, DmReview.complete_date >= since),
        )
        return list((await db.execute(stmt)).all())

    async def list_obsolete_notices(self, db: AsyncSession, user_id: str, since: datetime) -> list[Row]:
        """他人對「本人有版本之文件」發起之廢止（近 30 天）——供「文件廢止通知」呈現，明示發起人。

        排除本人自行發起之廢止（那屬撰寫者視角送審歷程）。回發起人 initiator_name（created_user）
        與審核者 reviewer_name（assigned_reviewer）姓名。時間新→舊由 service 端統一處理。
        """
        my_docs = (
            select(DmDocVersion.doc_id)
            .where(DmDocVersion.created_user == user_id, DmDocVersion.deleted == 0)
            .scalar_subquery()
        )
        initiator = aliased(DpUser)
        reviewer = aliased(DpUser)
        stmt = (
            select(
                DmReview.review_id,
                DmReview.doc_id,
                DmReview.status,
                DmReview.submit_date,
                DmReview.complete_date,
                DmDocument.doc_name,
                initiator.user_name.label("initiator_name"),
                reviewer.user_name.label("reviewer_name"),
            )
            .join(DmDocument, (DmReview.doc_id == DmDocument.doc_id) & (DmDocument.deleted == 0))
            .outerjoin(initiator, DmReview.created_user == initiator.user_id)
            .outerjoin(reviewer, DmReview.assigned_reviewer == reviewer.user_id)
            .where(
                DmReview.review_type == _OBSOLETE,
                DmReview.created_user != user_id,  # 本人發起者屬撰寫者視角，不重複
                DmReview.doc_id.in_(my_docs),
                # 僅廢止待簽核 / 已廢止才通知；退回 / 撤回代表文件回 PUBLISHED、草稿亦回草稿匣，無需通知
                DmReview.status.in_((_PENDING, _APPROVED)),
                or_(DmReview.submit_date >= since, DmReview.complete_date >= since),
            )
        )
        return list((await db.execute(stmt)).all())
