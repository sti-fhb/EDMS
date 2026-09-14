"""ET 邀請 model（ET_INVITATION）。

`ET_INVITATION` 為 **Email 邀請**紀錄（標籤自動邀請直接寫 `ET_ENROLLMENT`、不經本表）。

> 本檔原另含 `EtOwnerTransfer`（`ET_OWNER_TRANSFER`）。2026-09-14 裁示取消擁有者轉讓
> 功能——`ET_COURSE.OWNER_ID` 建立後即為終局，無人可於系統內變更——該 model 與表
> 一併移除（migration `b3e91c4a7d28`）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtInvitation(BaseModel):
    """Email 邀請紀錄（ET_INVITATION）。

    狀態流轉：`PENDING → JOINED` 或 `REVOKED`（後二者為終態）。
    「再次寄送」更新 `LAST_SENT_AT`、**不建新列**；「撤回」寫 `REVOKED` + `REVOKED_AT`，
    該 token 失效。

    `SEND_STATUS_CODE` 記錄最近一次寄信結果：**寄送失敗時 `STATUS` 維持 `PENDING`**
    （列於 US12 待加入清單、可重寄），不因寄信失敗回滾邀請。

    **`TOKEN_HASH` 只存雜湊、不存明文**（2026-08-20 安全檢查後改）：明文僅入信中連結，
    驗證時重新雜湊比對——比照平台 `DP_PWD_RESET.TOKEN_HASH`，使該表外洩無法反推可用連結。
    ⚠️ **尚無 `EXPIRES_AT`**：spec 未定義邀請連結之有效期（密碼重設有 30 分鐘 TTL，
    邀請則無），故未加欄位；已列為待 SA 裁示項（見 #185 留言）。
    """

    __tablename__ = "ET_INVITATION"
    __table_args__ = (
        PrimaryKeyConstraint("INVITATION_ID", name="PK_ET_INVITATION"),
        UniqueConstraint("TOKEN_HASH", name="UQ_ET_INVITATION_TOKEN_HASH"),
        Index("IX_ET_INVITATION_COURSE", "COURSE_ID"),
    )

    invitation_id: Mapped[int] = mapped_column("INVITATION_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_INVITATION_COURSE"), nullable=False
    )
    email: Mapped[str] = mapped_column("EMAIL", String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column("TOKEN_HASH", String(64), nullable=False)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False)
    sent_at: Mapped[datetime] = mapped_column("SENT_AT", DateTime(timezone=True), nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column("LAST_SENT_AT", DateTime(timezone=True), nullable=False)
    joined_at: Mapped[Optional[datetime]] = mapped_column("JOINED_AT", DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column("REVOKED_AT", DateTime(timezone=True), nullable=True)
    send_status_code: Mapped[Optional[str]] = mapped_column("SEND_STATUS_CODE", String(20), nullable=True)
