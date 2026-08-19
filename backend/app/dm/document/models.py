"""DM 文件核心 model（DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG / DM_DOC_READ）。

DM_DOCUMENT 為對外引用基準（DOC_ID）；身份屬性（名稱 / 分類 / func_name）編輯新版本時唯讀。
DM_DOCUMENT 與 DM_DOC_VERSION 互指（CURRENT_VERSION_ID ↔ DOC_ID）——`CURRENT_VERSION_ID`
採**邏輯 FK（純欄位、無 DB 外鍵）**打破循環，`DM_DOC_VERSION.DOC_ID` 為真 DB 外鍵。
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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class DmDocument(BaseModel):
    """文件主檔（DM_DOCUMENT）。

    DOC_ID 格式 `DM-{分類碼}-{6位流水號}`（草稿建立時配號）。STATUS：DRAFT / PENDING_REVIEW
    （僅首版送審）/ PUBLISHED（已發布文件之新版本送審期間維持此值）/ PENDING_OBSOLETE / OBSOLETE。
    **部分唯一索引**：同一 FUNC_CODE 於 CATEGORY='MANUAL' AND STATUS='PUBLISHED' 至多一份（手冊唯一）。
    CURRENT_VERSION_ID 為邏輯 FK（首版發布前 null）。CREATED_USER = 撰寫者。
    """

    __tablename__ = "DM_DOCUMENT"
    __table_args__ = (
        PrimaryKeyConstraint("DOC_ID", name="PK_DM_DOCUMENT"),
        Index("IX_DM_DOCUMENT_CATEGORY", "CATEGORY_CODE"),
        Index("IX_DM_DOCUMENT_STATUS", "STATUS"),
        # 手冊唯一：同 func_name 至多一份已發布手冊（research §5）
        Index(
            "UX_DM_DOCUMENT_MANUAL_FUNC",
            "FUNC_CODE",
            unique=True,
            postgresql_where=text("\"CATEGORY_CODE\" = 'MANUAL' AND \"STATUS\" = 'PUBLISHED'"),
        ),
    )

    doc_id: Mapped[str] = mapped_column("DOC_ID", String(20), nullable=False)
    doc_name: Mapped[str] = mapped_column("DOC_NAME", String(200), nullable=False)
    category_code: Mapped[str] = mapped_column(
        "CATEGORY_CODE",
        String(10),
        ForeignKey("DM_CATEGORY.CATEGORY_CODE", name="FK_DM_DOCUMENT_CATEGORY"),
        nullable=False,
    )
    func_code: Mapped[Optional[str]] = mapped_column(
        "FUNC_CODE", String(10), ForeignKey("DM_FUNC.FUNC_CODE", name="FK_DM_DOCUMENT_FUNC"), nullable=True
    )
    current_version_id: Mapped[Optional[int]] = mapped_column("CURRENT_VERSION_ID", BigInteger, nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False, default="DRAFT")


class DmDocVersion(BaseModel):
    """文件版本（DM_DOC_VERSION）。

    每版本單一檔案（DB 存 metadata、檔案存檔案系統）；所有版本永久保留（DELETED=0）。
    VERSION_NO 為撰寫者自行輸入之自由文字、同 DOC_ID 內不重複。STATUS：DRAFT / PENDING_REVIEW /
    PUBLISHED / SUPERSEDED / REJECTED。CREATED_USER = 該版本作者。
    """

    __tablename__ = "DM_DOC_VERSION"
    __table_args__ = (
        PrimaryKeyConstraint("VERSION_ID", name="PK_DM_DOC_VERSION"),
        UniqueConstraint("DOC_ID", "VERSION_NO", name="UQ_DM_DOC_VERSION_DOC_NO"),
        Index("IX_DM_DOC_VERSION_DOC", "DOC_ID"),
        # 每人每文件一份草稿（US5）：同 (DOC_ID, CREATED_USER) 至多一筆 STATUS='DRAFT'——並發後盾
        # （應用層另給友善 DM_DOC_009）。不同撰寫者可各自開草稿、互不阻擋。
        Index(
            "UX_DM_DOC_VERSION_ONE_DRAFT",
            "DOC_ID",
            "CREATED_USER",
            unique=True,
            postgresql_where=text("\"STATUS\" = 'DRAFT'"),
        ),
    )

    version_id: Mapped[int] = mapped_column("VERSION_ID", BigInteger, Identity(), nullable=False)
    doc_id: Mapped[str] = mapped_column(
        "DOC_ID", String(20), ForeignKey("DM_DOCUMENT.DOC_ID", name="FK_DM_DOC_VERSION_DOC"), nullable=False
    )
    version_no: Mapped[str] = mapped_column("VERSION_NO", String(20), nullable=False)
    change_summary: Mapped[str] = mapped_column("CHANGE_SUMMARY", Text, nullable=False)
    file_name: Mapped[str] = mapped_column("FILE_NAME", String(255), nullable=False)
    file_path: Mapped[str] = mapped_column("FILE_PATH", String(500), nullable=False)
    file_size: Mapped[int] = mapped_column("FILE_SIZE", BigInteger, nullable=False)
    file_mime: Mapped[str] = mapped_column("FILE_MIME", String(100), nullable=False)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False, default="DRAFT")
    approver_user_id: Mapped[Optional[str]] = mapped_column("APPROVER_USER_ID", String(20), nullable=True)
    published_date: Mapped[Optional[datetime]] = mapped_column("PUBLISHED_DATE", DateTime(timezone=True), nullable=True)


class DmDocTag(BaseModel):
    """文件標籤關聯（DM_DOC_TAG，明細）。

    文件 × 標籤多對多；含權限（AUDIENCE，必填≥1）與檢索（多選 AND）兩類。唯一約束 (DOC_ID, TAG_ID)。
    """

    __tablename__ = "DM_DOC_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("DOC_TAG_ID", name="PK_DM_DOC_TAG"),
        UniqueConstraint("DOC_ID", "TAG_ID", name="UQ_DM_DOC_TAG_DOC_TAG"),
        Index("IX_DM_DOC_TAG_DOC", "DOC_ID"),
        Index("IX_DM_DOC_TAG_TAG", "TAG_ID"),
    )

    doc_tag_id: Mapped[int] = mapped_column("DOC_TAG_ID", BigInteger, Identity(), nullable=False)
    doc_id: Mapped[str] = mapped_column(
        "DOC_ID", String(20), ForeignKey("DM_DOCUMENT.DOC_ID", name="FK_DM_DOC_TAG_DOC"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("DM_TAG.TAG_ID", name="FK_DM_DOC_TAG_TAG"), nullable=False
    )


class DmDocRead(AuditLogBaseModel):
    """閱讀紀錄（DM_DOC_READ，append-only 事件）。

    下載「目前發布版」之事件（預覽不記）；**下載者＝CREATED_USER、下載時間＝CREATED_DATE**
    （不另設 USER_ID / READ_TIME）；唯一約束 (DOC_ID, VERSION_ID, CREATED_USER)（同人同版一次已看）。
    """

    __tablename__ = "DM_DOC_READ"
    __table_args__ = (
        PrimaryKeyConstraint("READ_ID", name="PK_DM_DOC_READ"),
        UniqueConstraint("DOC_ID", "VERSION_ID", "CREATED_USER", name="UQ_DM_DOC_READ_DOC_VER_USER"),
        Index("IX_DM_DOC_READ_DOC", "DOC_ID"),
    )

    read_id: Mapped[int] = mapped_column("READ_ID", BigInteger, Identity(), nullable=False)
    doc_id: Mapped[str] = mapped_column(
        "DOC_ID", String(20), ForeignKey("DM_DOCUMENT.DOC_ID", name="FK_DM_DOC_READ_DOC"), nullable=False
    )
    version_id: Mapped[int] = mapped_column(
        "VERSION_ID", BigInteger, ForeignKey("DM_DOC_VERSION.VERSION_ID", name="FK_DM_DOC_READ_VER"), nullable=False
    )
