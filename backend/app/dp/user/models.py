from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class DpPwdReset(BaseModel):
    """一次性驗證 Token（DP_PWD_RESET）。

    忘記密碼（PWD_RESET）與帳號變更驗證（EMAIL_CHANGE）共用；
    明文 token 僅存在於信中連結，DB 只存其 SHA-256 雜湊（見 research §5）。
    同人同型重新申請時，舊列由服務層作廢。標準欄位由 BaseModel 繼承。
    """

    __tablename__ = "DP_PWD_RESET"
    __table_args__ = (
        PrimaryKeyConstraint("TOKEN_HASH", name="PK_DP_PWD_RESET"),
        Index("IX_DP_PWD_RESET_USER_TYPE_USED", "USER_ID", "TOKEN_TYPE", "USED_DATE"),
    )

    token_hash: Mapped[str] = mapped_column("TOKEN_HASH", String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        "USER_ID",
        String(20),
        ForeignKey("DP_USER.USER_ID", name="FK_DP_PWD_RESET_USER"),
        nullable=False,
    )
    token_type: Mapped[str] = mapped_column("TOKEN_TYPE", String(20), nullable=False)
    new_email: Mapped[Optional[str]] = mapped_column("NEW_EMAIL", String(255), nullable=True)
    expires_date: Mapped[datetime] = mapped_column("EXPIRES_DATE", DateTime(timezone=True), nullable=False)
    used_date: Mapped[Optional[datetime]] = mapped_column("USED_DATE", DateTime(timezone=True), nullable=True)


class DpPwdHistory(AuditLogBaseModel):
    """密碼歷程（DP_PWD_HIST，append-only；僅 CREATED_*）。

    每次設定密碼寫入一列；密碼重複性檢核取同人最近 N 筆（平台級參數，預設 3）比對。
    USER_ID + SEQ_NO 複合 PK，SEQ_NO 由服務層依同人遞增指派。
    """

    __tablename__ = "DP_PWD_HIST"
    __table_args__ = (PrimaryKeyConstraint("USER_ID", "SEQ_NO", name="PK_DP_PWD_HIST"),)

    user_id: Mapped[str] = mapped_column(
        "USER_ID",
        String(20),
        ForeignKey("DP_USER.USER_ID", name="FK_DP_PWD_HIST_USER"),
        nullable=False,
    )
    seq_no: Mapped[int] = mapped_column("SEQ_NO", Integer, nullable=False, autoincrement=False)
    pwd_hash: Mapped[str] = mapped_column("PWD_HASH", String(100), nullable=False)
