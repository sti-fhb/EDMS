"""ET 課程結構 model（ET_COURSE / ET_CHAPTER / ET_ITEM）。

課程狀態機：`DRAFT → PUBLISHED ⇄ CLOSED`（2026-07-02 變更：關閉**可逆**，原
`PENDING_CLOSE` 過渡狀態已移除）。`OWNER_ID` 與各 `USER_ID` 為邏輯 FK 指向平台
`DP_USER`（不設 DB 外鍵，比照 DM）。

教材三表（`ET_MATERIAL` / `ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC`）已於 2026-08-25
（#203）移至 `app/et/material/models.py`——教材為獨立聚合且其 CRUD 歸屬該子模組。
`ET_ITEM.MATERIAL_ID` 對其之 FK 以字串宣告，不需 Python 匯入。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtCourse(BaseModel):
    """課程主檔（ET_COURSE）。

    `INVITATION_CODE`：8 碼純數字、全域唯一；**草稿無碼、發布時系統自動產生**、
    發布後永久不可變更。DB 設 NULLable，發布後之非空由應用層保證。

    `OWNER_ID` 建立當下記錄、**永久不可變更**——例外為管理者代為轉讓（離職 / 帳號失能），
    須另寫 `ET_OWNER_TRANSFER` 稽核紀錄。

    `FIRST_PUBLISHED_AT` 僅供稽核、不顯示於 UI（開課日期語意已移交 `OPEN_START_AT`，
    歷經再開課不變）。`URGENT_REMIND_SENT` 於再開課重設起訖時歸 false。
    """

    __tablename__ = "ET_COURSE"
    __table_args__ = (
        PrimaryKeyConstraint("COURSE_ID", name="PK_ET_COURSE"),
        UniqueConstraint("INVITATION_CODE", name="UQ_ET_COURSE_INVITATION_CODE"),
        Index("IX_ET_COURSE_OWNER", "OWNER_ID"),
        Index("IX_ET_COURSE_STATUS", "STATUS"),
    )

    course_id: Mapped[int] = mapped_column("COURSE_ID", BigInteger, Identity(), nullable=False)
    course_name: Mapped[str] = mapped_column("COURSE_NAME", String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column("DESCRIPTION", Text, nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False, default="DRAFT")
    open_start_at: Mapped[Optional[datetime]] = mapped_column("OPEN_START_AT", DateTime(timezone=True), nullable=True)
    open_end_at: Mapped[Optional[datetime]] = mapped_column("OPEN_END_AT", DateTime(timezone=True), nullable=True)
    owner_id: Mapped[str] = mapped_column("OWNER_ID", String(20), nullable=False)
    invitation_code: Mapped[Optional[str]] = mapped_column("INVITATION_CODE", String(8), nullable=True)
    first_published_at: Mapped[Optional[datetime]] = mapped_column(
        "FIRST_PUBLISHED_AT", DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column("CLOSED_AT", DateTime(timezone=True), nullable=True)
    urgent_remind_sent: Mapped[bool] = mapped_column("URGENT_REMIND_SENT", Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)
    require_approval: Mapped[bool] = mapped_column("REQUIRE_APPROVAL", Boolean, nullable=False, default=False)


class EtChapter(BaseModel):
    """章節（ET_CHAPTER）——課程下之順序容器，學員須依序解鎖。

    刪除採軟刪除（`DELETED=1`），其下 `ET_ITEM` 連動軟刪除；學員於該章節之
    `ET_PROGRESS` / `ET_QUIZ_ATTEMPT_M` **亦連帶軟刪除**（`DELETED=1`）。

    > 2026-08-24（#202）變更，原為 hard delete。刪除章節是編輯**已發布**課程的常規
    > 操作，而學員成績不可重建——硬刪除把可回復的操作變成不可回復。
    > 代價：完課率 / 進度統計務必排除 `DELETED = 1`（分母以當前有效章節數計）。
    """

    __tablename__ = "ET_CHAPTER"
    __table_args__ = (
        PrimaryKeyConstraint("CHAPTER_ID", name="PK_ET_CHAPTER"),
        # 部分唯一索引（#202）：不變量是「**未刪除**之章節間順序不重複」。
        # 原全表唯一約束會讓已軟刪除之列繼續佔住順序，使 data-model 明訂之
        # 「後續章節順序自動遞補」無法實作。比照 DM 之 UX_* 部分索引前例。
        Index(
            "UX_ET_CHAPTER_COURSE_ORDER",
            "COURSE_ID",
            "SORT_ORDER",
            unique=True,
            postgresql_where=text('"DELETED" = 0'),
        ),
    )

    chapter_id: Mapped[int] = mapped_column("CHAPTER_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_CHAPTER_COURSE"), nullable=False
    )
    chapter_name: Mapped[str] = mapped_column("CHAPTER_NAME", String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtItem(BaseModel):
    """章節項目（ET_ITEM）——章節下之教材或測驗。

    `ITEM_TYPE` 與 `MATERIAL_ID` / `QUIZ_ID` **互斥**，以 CHECK constraint 於 DB 層保證：
    `MATERIAL` → `MATERIAL_ID` 必填且 `QUIZ_ID` 為 NULL；`QUIZ` 反之。
    """

    __tablename__ = "ET_ITEM"
    __table_args__ = (
        PrimaryKeyConstraint("ITEM_ID", name="PK_ET_ITEM"),
        # 部分唯一索引：不變量是「**未刪除**之項目間順序不重複」。全表唯一會讓
        # 已軟刪除的列繼續佔住順序，使刪除後的遞補撞鍵（同 ET_CHAPTER，見 #202）。
        Index(
            "UX_ET_ITEM_CHAPTER_ORDER",
            "CHAPTER_ID",
            "SORT_ORDER",
            unique=True,
            postgresql_where=text('"DELETED" = 0'),
        ),
        CheckConstraint(
            '("ITEM_TYPE" = \'MATERIAL\' AND "MATERIAL_ID" IS NOT NULL AND "QUIZ_ID" IS NULL) '
            'OR ("ITEM_TYPE" = \'QUIZ\' AND "QUIZ_ID" IS NOT NULL AND "MATERIAL_ID" IS NULL)',
            name="CK_ET_ITEM_TYPE_TARGET",
        ),
    )

    item_id: Mapped[int] = mapped_column("ITEM_ID", BigInteger, Identity(), nullable=False)
    chapter_id: Mapped[int] = mapped_column(
        "CHAPTER_ID", BigInteger, ForeignKey("ET_CHAPTER.CHAPTER_ID", name="FK_ET_ITEM_CHAPTER"), nullable=False
    )
    item_type: Mapped[str] = mapped_column("ITEM_TYPE", String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
    material_id: Mapped[Optional[int]] = mapped_column(
        "MATERIAL_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL.MATERIAL_ID", name="FK_ET_ITEM_MATERIAL"),
        nullable=True,
    )
    quiz_id: Mapped[Optional[int]] = mapped_column(
        "QUIZ_ID", BigInteger, ForeignKey("ET_QUIZ.QUIZ_ID", name="FK_ET_ITEM_QUIZ"), nullable=True
    )
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)
