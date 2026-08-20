"""ET 選課與學習進度 model（ET_ENROLLMENT / ET_PROGRESS / 影片進度 / 觀看區段）。

**影片進度為逐支影片**（2026-08-19 #179 變更）：原 `ET_PROGRESS` 兼存
`COVERAGE_PCT` / `LAST_POSITION_SEC`（項目層），在「同一教材含多支影片」時無法分別
記錄，導致 FR-ET-US5-05「**所有影片**累計覆蓋率 ≥ 80%」無法判定。兩欄已移至
`ET_PROGRESS_VIDEO`，區段表改掛 `VIDEO_ID`。
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtEnrollment(BaseModel):
    """選課關聯（ET_ENROLLMENT）——學員 × 課程。

    `IS_REMOVED=true` 之列前台不顯示，但學習歷史**完整保留**；移除後不計入完課率分母。
    學員無主動退出能力——退場僅能由教師於 US9 執行「移除學員」。

    標籤自動邀請（2026-07-02）：課程發布時依 `ET_COURSE_TAG × ET_USER_TAG` 取聯集去重
    （限具學員角色者；「全體」展開為全部學員角色者）批次 INSERT，`JOIN_SOURCE=TAG_DEFAULT`。
    """

    __tablename__ = "ET_ENROLLMENT"
    __table_args__ = (
        PrimaryKeyConstraint("ENROLLMENT_ID", name="PK_ET_ENROLLMENT"),
        UniqueConstraint("USER_ID", "COURSE_ID", name="UQ_ET_ENROLLMENT_USER_COURSE"),
        Index("IX_ET_ENROLLMENT_COURSE", "COURSE_ID"),
    )

    enrollment_id: Mapped[int] = mapped_column("ENROLLMENT_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_ENROLLMENT_COURSE"), nullable=False
    )
    join_source: Mapped[str] = mapped_column("JOIN_SOURCE", String(30), nullable=False)
    joined_at: Mapped[datetime] = mapped_column("JOINED_AT", DateTime(timezone=True), nullable=False)
    completion_status: Mapped[str] = mapped_column("COMPLETION_STATUS", String(20), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column("COMPLETED_AT", DateTime(timezone=True), nullable=True)
    is_removed: Mapped[bool] = mapped_column("IS_REMOVED", Boolean, nullable=False, default=False)
    removed_at: Mapped[Optional[datetime]] = mapped_column("REMOVED_AT", DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        "LAST_ACTIVITY_AT", DateTime(timezone=True), nullable=True
    )


class EtProgress(BaseModel):
    """學習進度（ET_PROGRESS）——**項目層**完成判定。

    `IS_COMPLETED`：含影片之教材＝該教材**所有未刪除影片**之
    `ET_PROGRESS_VIDEO.COVERAGE_PCT` 皆 ≥ 80%（缺任一支之進度紀錄視為 0%）；
    僅文件 / 說明文字＝開啟即 true；測驗＝及格即 true。

    逐支影片之覆蓋率與續看位置存於 `ET_PROGRESS_VIDEO`（2026-08-19 變更）。
    """

    __tablename__ = "ET_PROGRESS"
    __table_args__ = (
        PrimaryKeyConstraint("PROGRESS_ID", name="PK_ET_PROGRESS"),
        UniqueConstraint("USER_ID", "ITEM_ID", name="UQ_ET_PROGRESS_USER_ITEM"),
        Index("IX_ET_PROGRESS_COURSE", "COURSE_ID"),
    )

    progress_id: Mapped[int] = mapped_column("PROGRESS_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_PROGRESS_COURSE"), nullable=False
    )
    item_id: Mapped[int] = mapped_column(
        "ITEM_ID", BigInteger, ForeignKey("ET_ITEM.ITEM_ID", name="FK_ET_PROGRESS_ITEM"), nullable=False
    )
    is_completed: Mapped[bool] = mapped_column("IS_COMPLETED", Boolean, nullable=False, default=False)


class EtProgressVideo(BaseModel):
    """影片進度（ET_PROGRESS_VIDEO，2026-08-19 新增）——單支影片之覆蓋率與續看位置。

    `COVERAGE_PCT` 為**快取值**（供清單 / 統計快速讀取），權威來源仍為
    `ET_PROGRESS_INTERVAL`：學員離開頁面 normalize 後重算並寫回。上限 100%
    （重複觀看不加成，區段聯集去重）。影片軟刪除時本表連帶 hard delete。
    """

    __tablename__ = "ET_PROGRESS_VIDEO"
    __table_args__ = (
        PrimaryKeyConstraint("PROGRESS_VIDEO_ID", name="PK_ET_PROGRESS_VIDEO"),
        UniqueConstraint("USER_ID", "VIDEO_ID", name="UQ_ET_PROGRESS_VIDEO_USER_VIDEO"),
    )

    progress_video_id: Mapped[int] = mapped_column("PROGRESS_VIDEO_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    video_id: Mapped[int] = mapped_column(
        "VIDEO_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL_VIDEO.VIDEO_ID", name="FK_ET_PROGRESS_VIDEO_VIDEO"),
        nullable=False,
    )
    coverage_pct: Mapped[Decimal] = mapped_column("COVERAGE_PCT", Numeric(5, 2), nullable=False, default=0)
    last_position_sec: Mapped[Optional[int]] = mapped_column("LAST_POSITION_SEC", Integer, nullable=True)


class EtProgressInterval(BaseModel):
    """影片觀看區段（ET_PROGRESS_INTERVAL）——每段播放一列。

    以**獨立資料列**儲存而非 JSON 字串：避免 read-modify-write race，便於 SQL 直接聚合。
    每段播放（暫停 / 結束 / 跳轉）INSERT 一列；**不設唯一約束**（同一區間可重複播放）。

    學員離開頁面時 normalize：SELECT (USER_ID, VIDEO_ID) → 排序 → 合併重疊 / 鄰近區段
    → DELETE → INSERT 合併後結果，並回寫 `ET_PROGRESS_VIDEO.COVERAGE_PCT`。

    覆蓋率 = `SUM(END_SEC − START_SEC) ÷ ET_MATERIAL_VIDEO.DURATION_SEC`
    （normalize 前後皆可正確計算，因聚合方法相同）。`END_SEC` 不得超過該影片
    `DURATION_SEC`（應用層裁切，避免覆蓋率 > 100%）。
    """

    __tablename__ = "ET_PROGRESS_INTERVAL"
    __table_args__ = (
        PrimaryKeyConstraint("INTERVAL_ID", name="PK_ET_PROGRESS_INTERVAL"),
        Index("IX_ET_PROGRESS_INTERVAL_USER_VIDEO", "USER_ID", "VIDEO_ID"),
    )

    interval_id: Mapped[int] = mapped_column("INTERVAL_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    video_id: Mapped[int] = mapped_column(
        "VIDEO_ID",
        BigInteger,
        ForeignKey("ET_MATERIAL_VIDEO.VIDEO_ID", name="FK_ET_PROGRESS_INTERVAL_VIDEO"),
        nullable=False,
    )
    start_sec: Mapped[int] = mapped_column("START_SEC", Integer, nullable=False)
    end_sec: Mapped[int] = mapped_column("END_SEC", Integer, nullable=False)
