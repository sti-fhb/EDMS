"""DM 簽核 / 變更歷程 model（DM_REVIEW / DM_CHANGE_LOG）。

DM_REVIEW 一列代表一次送審週期（新增 / 新版本 / 廢止）；撤回重送以新列記錄、原列保留。
「同一文件不可同時兩種送審」以 **DB partial unique index**（同 DOC_ID 至多一筆 STATUS=PENDING）
保證，應用層再以 count 快速判斷給友善錯誤（DM_REVIEW_002），並以 IntegrityError 為並發後盾。
DM_CHANGE_LOG 為對外發布 / 廢止事件之公開變更歷程（append-only、不可竄改）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, PrimaryKeyConstraint, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class DmReview(BaseModel):
    """送審紀錄（DM_REVIEW）。

    REVIEW_TYPE：NEW / NEW_VERSION / OBSOLETE。STATUS：PENDING / APPROVED / REJECTED / WITHDRAWN。
    OBSOLETE_FILE_* 為廢止類選填單檔。ASSIGNED_REVIEWER 排除撰寫者本人（應用層）。
    """

    __tablename__ = "DM_REVIEW"
    __table_args__ = (
        PrimaryKeyConstraint("REVIEW_ID", name="PK_DM_REVIEW"),
        Index("IX_DM_REVIEW_DOC", "DOC_ID"),
        Index("IX_DM_REVIEW_STATUS", "STATUS"),
        Index("IX_DM_REVIEW_REVIEWER", "ASSIGNED_REVIEWER"),
        # 同一文件至多一筆進行中送審：DB 級保證（partial unique index），杜絕並發雙送審
        Index("UX_DM_REVIEW_ONE_PENDING", "DOC_ID", unique=True, postgresql_where=text("\"STATUS\" = 'PENDING'")),
    )

    review_id: Mapped[int] = mapped_column("REVIEW_ID", BigInteger, Identity(), nullable=False)
    doc_id: Mapped[str] = mapped_column(
        "DOC_ID", String(20), ForeignKey("DM_DOCUMENT.DOC_ID", name="FK_DM_REVIEW_DOC"), nullable=False
    )
    version_id: Mapped[Optional[int]] = mapped_column(
        "VERSION_ID", BigInteger, ForeignKey("DM_DOC_VERSION.VERSION_ID", name="FK_DM_REVIEW_VER"), nullable=True
    )
    review_type: Mapped[str] = mapped_column("REVIEW_TYPE", String(20), nullable=False)
    assigned_reviewer: Mapped[str] = mapped_column("ASSIGNED_REVIEWER", String(20), nullable=False)
    approver_user_id: Mapped[Optional[str]] = mapped_column("APPROVER_USER_ID", String(20), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False, default="PENDING")
    submit_date: Mapped[datetime] = mapped_column("SUBMIT_DATE", DateTime(timezone=True), nullable=False)
    complete_date: Mapped[Optional[datetime]] = mapped_column("COMPLETE_DATE", DateTime(timezone=True), nullable=True)
    #: OBSOLETE：**申請人**寫的廢止申請原因（`_reject_obsolete` 退回時會寫回，勿覆寫）；
    #: NEW / NEW_VERSION：審核者的退回原因（歷史欄位，新資料改讀 `reject_reason`）。
    reason: Mapped[Optional[str]] = mapped_column("REASON", Text, nullable=True)
    #: **審核者**退回時填寫的原因（#679）。語意唯一、不分 `review_type`。
    #:
    #: 新增此欄是因為 `REASON` 一欄兩義：對 OBSOLETE 它裝的是申請人的廢止申請原因（那是唯一
    #: 存放處），於是審核者對廢止申請的退回原因先前無處可放，只進稽核與 OBS_REJECT 通知——
    #: 而該通知自 #554 起是 MSG，系統沒有站內訊息畫面 ⇒ 申請人任何地方都看不到。
    #: 既有列為 NULL（#679 裁示不回填），畫面顯示「—」。
    reject_reason: Mapped[Optional[str]] = mapped_column("REJECT_REASON", Text, nullable=True)
    obsolete_file_name: Mapped[Optional[str]] = mapped_column("OBSOLETE_FILE_NAME", String(255), nullable=True)
    obsolete_file_path: Mapped[Optional[str]] = mapped_column("OBSOLETE_FILE_PATH", String(500), nullable=True)
    obsolete_file_size: Mapped[Optional[int]] = mapped_column("OBSOLETE_FILE_SIZE", BigInteger, nullable=True)
    obsolete_file_mime: Mapped[Optional[str]] = mapped_column("OBSOLETE_FILE_MIME", String(100), nullable=True)


class DmChangeLog(AuditLogBaseModel):
    """公開變更歷程（DM_CHANGE_LOG，append-only）。

    僅記錄對外發布版本之發布 / 廢止事件（OPERATION：PUBLISH / OBSOLETE）；永久保留不可竄改；
    供 DM05 跨文件查詢與 CSV 匯出。
    """

    __tablename__ = "DM_CHANGE_LOG"
    __table_args__ = (
        PrimaryKeyConstraint("CHANGE_LOG_ID", name="PK_DM_CHANGE_LOG"),
        Index("IX_DM_CHANGE_LOG_DOC", "DOC_ID"),
        Index("IX_DM_CHANGE_LOG_TIME", "OPERATION_TIME"),
    )

    change_log_id: Mapped[int] = mapped_column("CHANGE_LOG_ID", BigInteger, Identity(), nullable=False)
    doc_id: Mapped[str] = mapped_column(
        "DOC_ID", String(20), ForeignKey("DM_DOCUMENT.DOC_ID", name="FK_DM_CHANGE_LOG_DOC"), nullable=False
    )
    version_id: Mapped[Optional[int]] = mapped_column(
        "VERSION_ID", BigInteger, ForeignKey("DM_DOC_VERSION.VERSION_ID", name="FK_DM_CHANGE_LOG_VER"), nullable=True
    )
    operation: Mapped[str] = mapped_column("OPERATION", String(10), nullable=False)
    applicant_user_id: Mapped[str] = mapped_column("APPLICANT_USER_ID", String(20), nullable=False)
    approver_user_id: Mapped[str] = mapped_column("APPROVER_USER_ID", String(20), nullable=False)
    operation_time: Mapped[datetime] = mapped_column("OPERATION_TIME", DateTime(timezone=True), nullable=False)
    note: Mapped[Optional[str]] = mapped_column("NOTE", Text, nullable=True)
