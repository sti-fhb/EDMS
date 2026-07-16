from typing import Optional

from sqlalchemy import BigInteger, Identity, Index, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel


class DpAuditLog(AuditLogBaseModel):
    """操作歷程（DP_AUDIT_LOG，append-only；僅 CREATED_*；操作者＝CREATED_USER）。

    每筆操作寫入一列，不可修改 / 刪除。ROW_HASH 為鏈式完整性雜湊
    （本列內容 + 前列 ROW_HASH 的 SHA-256），由稽核服務（SRVDP003）計算填入。
    BEFORE_VALUE / AFTER_VALUE 以 TEXT 存 JSON 字串（非 JSONB，見 research §6）。
    不設 DB-level FK：CREATED_USER 可為 SYSTEM，且稽核紀錄採保留原則。

    落地要求（部署 / ops 層，非本 migration）：應用 DB 帳號對本表僅 GRANT INSERT / SELECT。
    """

    __tablename__ = "DP_AUDIT_LOG"
    __table_args__ = (
        PrimaryKeyConstraint("LOG_ID", name="PK_DP_AUDIT_LOG"),
        Index("IX_DP_AUDIT_LOG_CREATED_DATE", "CREATED_DATE"),
        Index("IX_DP_AUDIT_LOG_CREATED_USER_DATE", "CREATED_USER", "CREATED_DATE"),
        Index("IX_DP_AUDIT_LOG_MODULE_ACTION_DATE", "MODULE", "ACTION_TYPE", "CREATED_DATE"),
    )

    log_id: Mapped[int] = mapped_column("LOG_ID", BigInteger, Identity(), nullable=False)
    module: Mapped[str] = mapped_column("MODULE", String(5), nullable=False)
    func_name: Mapped[str] = mapped_column("FUNC_NAME", String(50), nullable=False)
    action_type: Mapped[str] = mapped_column("ACTION_TYPE", String(10), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column("TARGET_ID", String(100), nullable=True)
    result: Mapped[str] = mapped_column("RESULT", String(10), nullable=False)
    description: Mapped[Optional[str]] = mapped_column("DESCRIPTION", String(500), nullable=True)
    source_ip: Mapped[Optional[str]] = mapped_column("SOURCE_IP", String(45), nullable=True)
    before_value: Mapped[Optional[str]] = mapped_column("BEFORE_VALUE", Text, nullable=True)
    after_value: Mapped[Optional[str]] = mapped_column("AFTER_VALUE", Text, nullable=True)
    row_hash: Mapped[str] = mapped_column("ROW_HASH", String(64), nullable=False)
