"""DM 使用者角色 model（DM_USER_ROLE / DM_USER_ROLE_LOG）。

DM 權限自管（4 角色 DM_ADMIN / DM_EDITOR / DM_REVIEWER / DM_VIEWER），與 ET 角色獨立。
`USER_ID` 邏輯 FK 指向平台 `DP_USER.USER_ID`（跨模組鬆耦合、不設 DB 外鍵，比照 DP 慣例）。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class DmUserRole(BaseModel):
    """DM 使用者角色指派（DM_USER_ROLE）。

    同一使用者可多列（複選、聯集）；唯一約束 (USER_ID, ROLE_CODE)。
    標準欄位之 UPDATED_USER / UPDATED_DATE 即權限管理「最後異動」欄之來源。
    完整異動歷史另寫 DM_USER_ROLE_LOG。
    """

    __tablename__ = "DM_USER_ROLE"
    __table_args__ = (
        PrimaryKeyConstraint("DM_USER_ROLE_ID", name="PK_DM_USER_ROLE"),
        UniqueConstraint("USER_ID", "ROLE_CODE", name="UQ_DM_USER_ROLE_USER_ROLE"),
        Index("IX_DM_USER_ROLE_USER", "USER_ID"),
    )

    dm_user_role_id: Mapped[int] = mapped_column("DM_USER_ROLE_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    role_code: Mapped[str] = mapped_column("ROLE_CODE", String(20), nullable=False)


class DmUserRoleLog(AuditLogBaseModel):
    """角色異動紀錄（DM_USER_ROLE_LOG，append-only；僅 CREATED_*）。

    每次角色勾選 / 取消寫入一列，永久保留、不修改不刪除；DM 不提供查詢 UI。
    OPERATOR_USER_ID / ACTION_TIME 為業務欄位（與標準 CREATED_* 併存，供稽核追溯）。
    """

    __tablename__ = "DM_USER_ROLE_LOG"
    __table_args__ = (
        PrimaryKeyConstraint("LOG_ID", name="PK_DM_USER_ROLE_LOG"),
        Index("IX_DM_USER_ROLE_LOG_TARGET", "TARGET_USER_ID"),
    )

    log_id: Mapped[int] = mapped_column("LOG_ID", BigInteger, Identity(), nullable=False)
    target_user_id: Mapped[str] = mapped_column("TARGET_USER_ID", String(20), nullable=False)
    role_code: Mapped[str] = mapped_column("ROLE_CODE", String(20), nullable=False)
    action: Mapped[str] = mapped_column("ACTION", String(10), nullable=False)
    operator_user_id: Mapped[str] = mapped_column("OPERATOR_USER_ID", String(20), nullable=False)
    action_time: Mapped[datetime] = mapped_column("ACTION_TIME", DateTime(timezone=True), nullable=False)
