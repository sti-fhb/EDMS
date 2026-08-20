"""ET 課程結構 model（ET_COURSE / ET_CHAPTER / ET_ITEM / ET_MATERIAL / 教材子表）。

課程狀態機：`DRAFT → PUBLISHED ⇄ CLOSED`（2026-07-02 變更：關閉**可逆**，原
`PENDING_CLOSE` 過渡狀態已移除）。`OWNER_ID` 與各 `USER_ID` 為邏輯 FK 指向平台
`DP_USER`（不設 DB 外鍵，比照 DM）。

教材媒材於 2026-08-19（#179）自暫時欄位**正式拆為 1:N 子表**：原
`ET_MATERIAL.VIDEO_FILE_PATH`（單一路徑）與 `DM_DOC_IDS`（CSV 字串）存不下多支影片，
亦無法承載逐支影片之長度與順序（覆蓋率判定必需）。
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
    `ET_PROGRESS` / `ET_QUIZ_ATTEMPT_M` 則連帶 **hard delete**（軟刪除分流：
    本體保留供稽核、學員紀錄孤兒化無意義）。
    """

    __tablename__ = "ET_CHAPTER"
    __table_args__ = (
        PrimaryKeyConstraint("CHAPTER_ID", name="PK_ET_CHAPTER"),
        UniqueConstraint("COURSE_ID", "SORT_ORDER", name="UQ_ET_CHAPTER_COURSE_ORDER"),
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
        UniqueConstraint("CHAPTER_ID", "SORT_ORDER", name="UQ_ET_ITEM_CHAPTER_ORDER"),
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


class EtMaterial(BaseModel):
    """教材內容（ET_MATERIAL）——媒材容器。

    三類媒材皆可選填且可組合：影片見 `ET_MATERIAL_VIDEO`（0..N）、DM 文件見
    `ET_MATERIAL_DOC`（0..N）、說明文字為本表 `DESCRIPTION_HTML`。
    三者**至少擇一有值**方為有效教材（應用層檢核；空教材不得存檔）。
    """

    __tablename__ = "ET_MATERIAL"
    __table_args__ = (PrimaryKeyConstraint("MATERIAL_ID", name="PK_ET_MATERIAL"),)

    material_id: Mapped[int] = mapped_column("MATERIAL_ID", BigInteger, Identity(), nullable=False)
    material_name: Mapped[str] = mapped_column("MATERIAL_NAME", String(100), nullable=False)
    description_html: Mapped[Optional[str]] = mapped_column("DESCRIPTION_HTML", Text, nullable=True)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtMaterialVideo(BaseModel):
    """教材影片（ET_MATERIAL_VIDEO，2026-08-19 新增）。

    `DURATION_SEC` 為**覆蓋率公式之分母**（覆蓋率 = 已觀看區段聯集秒數 ÷ DURATION_SEC），
    故 NOT NULL：上傳時由系統自檔案 metadata 取得並寫入，**取得失敗不得存檔**——
    否則該影片覆蓋率永遠算不出、章節永久無法解鎖。

    刪除採軟刪除；學員於該影片之 `ET_PROGRESS_VIDEO` / `ET_PROGRESS_INTERVAL`
    連帶 hard delete。
    """

    __tablename__ = "ET_MATERIAL_VIDEO"
    __table_args__ = (
        PrimaryKeyConstraint("VIDEO_ID", name="PK_ET_MATERIAL_VIDEO"),
        UniqueConstraint("MATERIAL_ID", "SORT_ORDER", name="UQ_ET_MATERIAL_VIDEO_ORDER"),
    )

    video_id: Mapped[int] = mapped_column("VIDEO_ID", BigInteger, Identity(), nullable=False)
    material_id: Mapped[int] = mapped_column(
        "MATERIAL_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL.MATERIAL_ID", name="FK_ET_MATERIAL_VIDEO_MATERIAL"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column("FILE_PATH", String(500), nullable=False)
    file_name: Mapped[str] = mapped_column("FILE_NAME", String(200), nullable=False)
    duration_sec: Mapped[int] = mapped_column("DURATION_SEC", Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column("FILE_SIZE_BYTES", BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)


class EtMaterialDoc(BaseModel):
    """教材引用之 DM 文件（ET_MATERIAL_DOC，2026-08-19 新增）。

    `DOC_ID` 格式 `DM-{分類碼}-{6位流水號}`（如 `DM-TRAINING-000007`）、**VARCHAR(20)
    非數值型**、且**非 DB 外鍵**——跨模組不設實體外鍵，內容經 SRVDM001 查詢
    （per sti-backend-boundaries）。

    僅存編號、不存內容與版本號：恆以 SRVDM001 取當前發布版，DM 發布新版 ET 自動
    取得最新版（無快取延遲）。
    """

    __tablename__ = "ET_MATERIAL_DOC"
    __table_args__ = (
        PrimaryKeyConstraint("MAT_DOC_ID", name="PK_ET_MATERIAL_DOC"),
        UniqueConstraint("MATERIAL_ID", "DOC_ID", name="UQ_ET_MATERIAL_DOC_MATERIAL_DOC"),
    )

    mat_doc_id: Mapped[int] = mapped_column("MAT_DOC_ID", BigInteger, Identity(), nullable=False)
    material_id: Mapped[int] = mapped_column(
        "MATERIAL_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL.MATERIAL_ID", name="FK_ET_MATERIAL_DOC_MATERIAL"),
        nullable=False,
    )
    doc_id: Mapped[str] = mapped_column("DOC_ID", String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
