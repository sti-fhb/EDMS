from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel, BaseModelHardDelete


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


class DpPendingRegistration(BaseModelHardDelete):
    """待驗證的自助註冊（DP_PENDING_REGISTRATION）。

    US2 改為「Email 驗證後啟用」（#56，方案 B）：註冊當下**不寫 DP_USER**，先把註冊申請
    （Email / 姓名 / 密碼雜湊 + 一次性驗證 token）暫存於本表；點驗證連結通過才 INSERT DP_USER。
    如此 DP_USER 只存已驗證帳號，登入 / 忘記密碼 / 使用者管理等不必處理未驗證半成品。

    一 Email 一筆待驗證（EMAIL UNIQUE）：重新註冊 / 重寄時以 Email 覆蓋（刪舊列 + 插新）。
    明文 token 僅入信中連結，本表只存其 SHA-256（同 DP_PWD_RESET）。consume / 逾時後硬刪除
    （BaseModelHardDelete，無 DELETED），逾期未驗證列由排程清理。

    兩種來源以 KIND 區分（US4 #67）：
    - SELF_REGISTER（US2 自助註冊）：建立即帶 PWD_HASH，啟用時搬入 DP_USER。
    - ADMIN_INVITE（US4 管理者邀請）：建立時 PWD_HASH 為 NULL，使用者於啟用連結自設密碼才回填。
    """

    __tablename__ = "DP_PENDING_REGISTRATION"
    __table_args__ = (
        PrimaryKeyConstraint("TOKEN_HASH", name="PK_DP_PENDING_REGISTRATION"),
        UniqueConstraint("EMAIL", name="UQ_DP_PENDING_REGISTRATION_EMAIL"),
    )

    token_hash: Mapped[str] = mapped_column("TOKEN_HASH", String(64), nullable=False)
    email: Mapped[str] = mapped_column("EMAIL", String(255), nullable=False)
    user_name: Mapped[str] = mapped_column("USER_NAME", String(50), nullable=False)
    # ADMIN_INVITE 建立時為 NULL（使用者啟用時自設密碼回填）；SELF_REGISTER 建立即有值
    pwd_hash: Mapped[Optional[str]] = mapped_column("PWD_HASH", String(100), nullable=True)
    kind: Mapped[str] = mapped_column("KIND", String(20), nullable=False)
    expires_date: Mapped[datetime] = mapped_column("EXPIRES_DATE", DateTime(timezone=True), nullable=False)


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
