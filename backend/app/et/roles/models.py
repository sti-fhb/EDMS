"""ET 使用者角色 model（ET_USER_ROLE）。

ET 權限自管（3 角色 ADMIN / TEACHER / STUDENT，可多重指派、權限取聯集），與 DM 角色獨立。
`USER_ID` 為**邏輯 FK** 指向平台 `DP_USER.USER_ID`（跨模組鬆耦合、不設 DB 外鍵，比照
`app/dm/roles/models.py` 與 DP 慣例）。

標準欄位之 `UPDATED_USER` / `UPDATED_DATE` 即 DP 後台權限管理「最後異動」欄之來源
（module-callbacks §3 之 `AssignmentView.last_modified_*`）。
"""

from sqlalchemy import BigInteger, Boolean, Identity, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtUserRole(BaseModel):
    """ET 使用者角色指派（ET_USER_ROLE）。

    同一使用者可多列（複選、聯集）；唯一約束 (USER_ID, ROLE)。
    `IS_ACTIVE` 供停用角色而不刪列——角色判定一律只認 `IS_ACTIVE=true` 且未軟刪除者。

    **不檢核「至少 1 個啟用中管理者」**（per et/spec.md 設計取捨：情境極少，
    由 IT 透過 DB 恢復即可，增加檢核徒增系統複雜度）。
    """

    __tablename__ = "ET_USER_ROLE"
    __table_args__ = (
        PrimaryKeyConstraint("ROLE_ID", name="PK_ET_USER_ROLE"),
        UniqueConstraint("USER_ID", "ROLE", name="UQ_ET_USER_ROLE_USER_ROLE"),
        Index("IX_ET_USER_ROLE_USER", "USER_ID"),
    )

    role_id: Mapped[int] = mapped_column("ROLE_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    role: Mapped[str] = mapped_column("ROLE", String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column("IS_ACTIVE", Boolean, nullable=False, default=True)
