"""文件變更歷程查詢資料存取（US11，唯讀）。

查 `DM_CHANGE_LOG`（append-only，PUBLISH / OBSOLETE 兩類），join `DM_DOCUMENT`（文件名）、
`DM_DOC_VERSION`（版本號）、`DP_USER`×2（申請人 / 核准人姓名）。DP_USER / 跨子模組 join 為唯讀查詢
例外（sti-backend-boundaries §報表/查詢：僅 SELECT、不重實作他模組業務規則）。

keyword 需比對 `DP_USER.USER_NAME`（申請人 / 核准人姓名）故 join 內含別名——count 與 list 共用同一
`enriched_select`（含 join + where），避免 count 漏掉 keyword 之姓名比對。
"""

from datetime import date

from sqlalchemy import Row, Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.dm.document.models import DmDocument, DmDocVersion
from app.dm.review.models import DmChangeLog
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）


class ChangeLogRepository:
    """公開變更歷程查詢（多條件 + 分頁）。"""

    def enriched_select(
        self,
        *,
        keyword: str | None,
        operation: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> Select:
        """組 enriched select（含 join + where + 排序）；供 count（subquery）與 list 共用。

        keyword 單一輸入同時比對申請人 / 核准人之「帳號或姓名」（FR-002）。日期比對 OPERATION_TIME。
        """
        applicant = aliased(DpUser)
        approver = aliased(DpUser)
        conds = []
        if operation:
            conds.append(DmChangeLog.operation == operation)
        if date_from:
            conds.append(func.date(DmChangeLog.operation_time) >= date_from)
        if date_to:
            conds.append(func.date(DmChangeLog.operation_time) <= date_to)
        if keyword:
            # 「帳號或姓名」（FR-002）：EDMS 登入以 email 為帳號、USER_ID 為內部 GUID（使用者不可見），
            # 故比對申請人 / 核准人之 DP_USER.email（帳號）與 user_name（姓名），不比對 GUID USER_ID。
            pattern = f"%{keyword}%"
            conds.append(
                or_(
                    applicant.email.ilike(pattern),
                    applicant.user_name.ilike(pattern),
                    approver.email.ilike(pattern),
                    approver.user_name.ilike(pattern),
                )
            )
        return (
            select(
                DmChangeLog.change_log_id,
                DmChangeLog.operation_time,
                DmChangeLog.operation,
                DmChangeLog.applicant_user_id.label("applicant_id"),
                applicant.user_name.label("applicant_name"),
                DmChangeLog.approver_user_id.label("approver_id"),
                approver.user_name.label("approver_name"),
                DmChangeLog.doc_id,
                DmDocument.doc_name,
                DmDocVersion.version_no,
                # 備註（FR-003）：發布＝該版本變更摘要、廢止＝廢止原因（NOTE）。發布事件之 NOTE 未由寫入端
                # 填入（見 review/center_service PUBLISH 分支），故發布列改由 DM_DOC_VERSION.change_summary
                # 取，涵蓋既有已寫入列；廢止列仍取 NOTE（廢止原因，US8 必填）。
                case(
                    (DmChangeLog.operation == "PUBLISH", DmDocVersion.change_summary),
                    else_=DmChangeLog.note,
                ).label("note"),
            )
            .select_from(DmChangeLog)
            .join(DmDocument, DmChangeLog.doc_id == DmDocument.doc_id)
            .outerjoin(DmDocVersion, DmChangeLog.version_id == DmDocVersion.version_id)
            .outerjoin(applicant, DmChangeLog.applicant_user_id == applicant.user_id)
            .outerjoin(approver, DmChangeLog.approver_user_id == approver.user_id)
            .where(*conds)
            .order_by(DmChangeLog.operation_time.desc(), DmChangeLog.change_log_id.desc())
        )

    async def count(self, db: AsyncSession, stmt: Select) -> int:
        return await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0

    async def list_page(self, db: AsyncSession, stmt: Select, *, offset: int, limit: int) -> list[Row]:
        return list((await db.execute(stmt.offset(offset).limit(limit))).all())

    async def list_all(self, db: AsyncSession, stmt: Select) -> list[Row]:
        """匯出用：無分頁（依時間新→舊）。"""
        return list((await db.execute(stmt)).all())
