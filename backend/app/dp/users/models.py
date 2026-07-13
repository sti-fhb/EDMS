from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class DpUser(BaseModel):
    """平台使用者主檔（DP_USER）。

    EDMS 單一組織、無站點維度；EMAIL 為帳號且一般個資不加密儲存。
    不建 DP_SESSION（無 Refresh Token，改以 JWT auth_time 換發，見 research §1）。
    標準欄位（CREATED_* / UPDATED_* / RES_ID / DELETED）由 BaseModel 繼承。
    """

    __tablename__ = "DP_USER"
    __table_args__ = (
        PrimaryKeyConstraint("USER_ID", name="PK_DP_USER"),
        UniqueConstraint("EMAIL", name="UQ_DP_USER_EMAIL"),
    )

    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    email: Mapped[str] = mapped_column("EMAIL", String(255), nullable=False)
    pwd_hash: Mapped[str] = mapped_column("PWD_HASH", String(100), nullable=False)
    user_name: Mapped[str] = mapped_column("USER_NAME", String(50), nullable=False)
    status: Mapped[str] = mapped_column("STATUS", String(10), nullable=False, default="ACTIVE")
    login_fail_count: Mapped[int] = mapped_column("LOGIN_FAIL_COUNT", Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column("LOCKED_UNTIL", DateTime(timezone=True), nullable=True)
    last_login_date: Mapped[Optional[datetime]] = mapped_column(
        "LAST_LOGIN_DATE", DateTime(timezone=True), nullable=True
    )
    pending_email: Mapped[Optional[str]] = mapped_column("PENDING_EMAIL", String(255), nullable=True)
    pwd_changed_date: Mapped[datetime] = mapped_column("PWD_CHANGED_DATE", DateTime(timezone=True), nullable=False)
    must_change_pwd: Mapped[bool] = mapped_column("MUST_CHANGE_PWD", Boolean, nullable=False, default=False)
