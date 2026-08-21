"""ET 週統計快照 model（ET_WEEKLY_STAT）。

由排程 SCHET001 每週寫入（課程 × 週次），供週報「與上週比較」與歷史回查。
**append-only**——不回頭修改既有快照；僅統計開放中課程。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel


class EtWeeklyStat(AuditLogBaseModel):
    """週統計快照（ET_WEEKLY_STAT；append-only、僅 CREATED_*）。

    `(COURSE_ID, STAT_DATE)` 唯一。週報之「與上週比較」= 本次快照 − 前一次快照；
    某課程無上週快照時該欄顯示「—」而非錯誤。

    `COMPLETION_RATE` = 已完課 ÷ 已加入（**不含已移除**）。
    """

    __tablename__ = "ET_WEEKLY_STAT"
    __table_args__ = (
        PrimaryKeyConstraint("STAT_ID", name="PK_ET_WEEKLY_STAT"),
        UniqueConstraint("COURSE_ID", "STAT_DATE", name="UQ_ET_WEEKLY_STAT_COURSE_DATE"),
    )

    stat_id: Mapped[int] = mapped_column("STAT_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_WEEKLY_STAT_COURSE"), nullable=False
    )
    stat_date: Mapped[date] = mapped_column("STAT_DATE", Date, nullable=False)
    avg_progress_pct: Mapped[Decimal] = mapped_column("AVG_PROGRESS_PCT", Numeric(5, 2), nullable=False)
    cnt_not_started: Mapped[int] = mapped_column("CNT_NOT_STARTED", Integer, nullable=False)
    cnt_in_progress: Mapped[int] = mapped_column("CNT_IN_PROGRESS", Integer, nullable=False)
    cnt_completed: Mapped[int] = mapped_column("CNT_COMPLETED", Integer, nullable=False)
    completion_rate: Mapped[Decimal] = mapped_column("COMPLETION_RATE", Numeric(5, 2), nullable=False)
    cnt_enrolled: Mapped[int] = mapped_column("CNT_ENROLLED", Integer, nullable=False)
