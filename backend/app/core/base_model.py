from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BaseModel(Base):
    """所有 IF Table 共用的 8 個標準欄位，每張 Table 必須繼承此 class。
    各 Table 自行定義 PK，不由 BaseModel 提供。
    """

    __abstract__ = True

    created_user: Mapped[str] = mapped_column("CREATED_USER", String(20), nullable=False)
    created_date: Mapped[datetime] = mapped_column("CREATED_DATE", DateTime(timezone=True), nullable=False)
    created_site: Mapped[str] = mapped_column("CREATED_SITE", String(5), nullable=False)
    updated_user: Mapped[Optional[str]] = mapped_column("UPDATED_USER", String(20), nullable=True)
    updated_date: Mapped[Optional[datetime]] = mapped_column("UPDATED_DATE", DateTime(timezone=True), nullable=True)
    updated_site: Mapped[Optional[str]] = mapped_column("UPDATED_SITE", String(5), nullable=True)
    res_id: Mapped[Optional[str]] = mapped_column("RES_ID", String(30), nullable=True)
    deleted: Mapped[int] = mapped_column("DELETED", Integer, default=0, nullable=False)


class BaseModelNoResId(Base):
    """標準欄位（不含 RES_ID），用於業務欄位已佔用 RES_ID 的 Table。
    適用：選單、角色選單對應、Session 等 Table。
    """

    __abstract__ = True

    created_user: Mapped[str] = mapped_column("CREATED_USER", String(20), nullable=False)
    created_date: Mapped[datetime] = mapped_column("CREATED_DATE", DateTime(timezone=True), nullable=False)
    created_site: Mapped[str] = mapped_column("CREATED_SITE", String(5), nullable=False)
    updated_user: Mapped[Optional[str]] = mapped_column("UPDATED_USER", String(20), nullable=True)
    updated_date: Mapped[Optional[datetime]] = mapped_column("UPDATED_DATE", DateTime(timezone=True), nullable=True)
    updated_site: Mapped[Optional[str]] = mapped_column("UPDATED_SITE", String(5), nullable=True)
    deleted: Mapped[int] = mapped_column("DELETED", Integer, default=0, nullable=False)


class AuditLogBaseModel(Base):
    """稽核日誌專用基底（append-only）。
    僅含 CREATED 三欄，無 UPDATED_* / DELETED / RES_ID。
    RES_ID 為業務欄，由 AuditLog 自行定義。
    """

    __abstract__ = True

    created_user: Mapped[str] = mapped_column("CREATED_USER", String(20), nullable=False)
    created_date: Mapped[datetime] = mapped_column("CREATED_DATE", DateTime(timezone=True), nullable=False)
    created_site: Mapped[str] = mapped_column("CREATED_SITE", String(5), nullable=False)


class BaseModelHardDelete(Base):
    """硬刪除例外表標準欄位（含 RES_ID，**不含 DELETED**）。

    適用：代表實體設備、刪除即下線、不需保留歷史的 Table。
    硬刪除清單與理由詳見 sti-backend-modules.md §刪除策略。
    """

    __abstract__ = True

    created_user: Mapped[str] = mapped_column("CREATED_USER", String(20), nullable=False)
    created_date: Mapped[datetime] = mapped_column("CREATED_DATE", DateTime(timezone=True), nullable=False)
    created_site: Mapped[str] = mapped_column("CREATED_SITE", String(5), nullable=False)
    updated_user: Mapped[Optional[str]] = mapped_column("UPDATED_USER", String(20), nullable=True)
    updated_date: Mapped[Optional[datetime]] = mapped_column("UPDATED_DATE", DateTime(timezone=True), nullable=True)
    updated_site: Mapped[Optional[str]] = mapped_column("UPDATED_SITE", String(5), nullable=True)
    res_id: Mapped[Optional[str]] = mapped_column("RES_ID", String(30), nullable=True)
