from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class DpSchedule(BaseModel):
    """排程註冊表（DP_SCHEDULE）。

    JOB_ID 格式 SCH{模組}{3碼}（如 SCHDP001）。HANDLER_REF 為 Python dotted path，
    由排程引擎動態 import；IS_ENABLED 由 DB / 部署管理、不開放 UI。
    LAST_RUN_DATE / LAST_RUN_STATUS 於每次執行後更新。標準欄位由 BaseModel 繼承。
    """

    __tablename__ = "DP_SCHEDULE"
    __table_args__ = (PrimaryKeyConstraint("JOB_ID", name="PK_DP_SCHEDULE"),)

    job_id: Mapped[str] = mapped_column("JOB_ID", String(20), nullable=False)
    job_name: Mapped[str] = mapped_column("JOB_NAME", String(100), nullable=False)
    module: Mapped[str] = mapped_column("MODULE", String(5), nullable=False)
    cron_expr: Mapped[str] = mapped_column("CRON_EXPR", String(50), nullable=False)
    handler_ref: Mapped[str] = mapped_column("HANDLER_REF", String(200), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)
    last_run_date: Mapped[Optional[datetime]] = mapped_column("LAST_RUN_DATE", DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[Optional[str]] = mapped_column("LAST_RUN_STATUS", String(10), nullable=True)


class DpScheduleLog(AuditLogBaseModel):
    """排程執行歷程（DP_SCHEDULE_LOG，append-only；僅 CREATED_*）。

    每次排程觸發寫入一列；STATUS 為 SUCCESS / FAILED / SKIPPED。
    worker 以 (JOB_ID, START_DATE) 索引查詢某 job 的執行歷程。
    """

    __tablename__ = "DP_SCHEDULE_LOG"
    __table_args__ = (
        PrimaryKeyConstraint("LOG_ID", name="PK_DP_SCHEDULE_LOG"),
        Index("IX_DP_SCHEDULE_LOG_JOB_START", "JOB_ID", "START_DATE"),
    )

    log_id: Mapped[int] = mapped_column("LOG_ID", BigInteger, Identity(), nullable=False)
    job_id: Mapped[str] = mapped_column(
        "JOB_ID",
        String(20),
        ForeignKey("DP_SCHEDULE.JOB_ID", name="FK_DP_SCHEDULE_LOG_JOB"),
        nullable=False,
    )
    start_date: Mapped[datetime] = mapped_column("START_DATE", DateTime(timezone=True), nullable=False)
    end_date: Mapped[Optional[datetime]] = mapped_column("END_DATE", DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(10), nullable=False)
    error_msg: Mapped[Optional[str]] = mapped_column("ERROR_MSG", String(1000), nullable=True)
