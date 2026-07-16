from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel, BaseModelNoDelete


class DpNotifyTemplate(BaseModel):
    """通知範本（DP_NOTIFY_TEMPLATE）。

    MODULE + TEMPLATE_CODE 複合 PK；TEMPLATE_CODE 為固定事件代碼（種子建立，不可新增/刪除）。
    IS_SYSTEM=true（MODULE=DP 系統信）者不可停用/刪除，僅可編輯主旨內文。
    CHANNEL 僅作為是否寄 Email 之開關依據。VERSION 為樂觀鎖版本
    （ORM version_id_col 綁定待範本更新服務再接，本階段僅建欄位）。
    標準欄位由 BaseModel 繼承。
    """

    __tablename__ = "DP_NOTIFY_TEMPLATE"
    __table_args__ = (PrimaryKeyConstraint("MODULE", "TEMPLATE_CODE", name="PK_DP_NOTIFY_TEMPLATE"),)

    module: Mapped[str] = mapped_column("MODULE", String(5), nullable=False)
    template_code: Mapped[str] = mapped_column("TEMPLATE_CODE", String(30), nullable=False)
    template_name: Mapped[str] = mapped_column("TEMPLATE_NAME", String(100), nullable=False)
    subject: Mapped[str] = mapped_column("SUBJECT", String(200), nullable=False)
    body: Mapped[str] = mapped_column("BODY", Text, nullable=False)
    variables: Mapped[Optional[str]] = mapped_column("VARIABLES", String(500), nullable=True)
    channel: Mapped[str] = mapped_column("CHANNEL", String(10), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column("IS_SYSTEM", Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=1)


class DpEmailLog(BaseModelNoDelete):
    """寄件 outbox（DP_EMAIL_LOG）。

    一列一收件人，單筆失敗獨立重試。新增後只更新狀態（STATUS / RETRY_COUNT /
    ERROR_MSG / SENT_DATE），保留全部紀錄、永不刪除（故用 BaseModelNoDelete）。
    SUBJECT / BODY 為渲染後快照。worker 以 (STATUS, CREATED_DATE) 索引輪詢待寄件。
    """

    __tablename__ = "DP_EMAIL_LOG"
    __table_args__ = (
        PrimaryKeyConstraint("MESSAGE_ID", name="PK_DP_EMAIL_LOG"),
        Index("IX_DP_EMAIL_LOG_STATUS_CREATED", "STATUS", "CREATED_DATE"),
    )

    message_id: Mapped[int] = mapped_column("MESSAGE_ID", BigInteger, Identity(), nullable=False)
    module: Mapped[str] = mapped_column("MODULE", String(5), nullable=False)
    template_code: Mapped[str] = mapped_column("TEMPLATE_CODE", String(30), nullable=False)
    caller_module: Mapped[str] = mapped_column("CALLER_MODULE", String(5), nullable=False)
    recipient: Mapped[str] = mapped_column("RECIPIENT", String(255), nullable=False)
    subject: Mapped[str] = mapped_column("SUBJECT", String(200), nullable=False)
    body: Mapped[str] = mapped_column("BODY", Text, nullable=False)
    status: Mapped[str] = mapped_column("STATUS", String(10), nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column("RETRY_COUNT", Integer, nullable=False, default=0)
    error_msg: Mapped[Optional[str]] = mapped_column("ERROR_MSG", String(500), nullable=True)
    sent_date: Mapped[Optional[datetime]] = mapped_column("SENT_DATE", DateTime(timezone=True), nullable=True)
