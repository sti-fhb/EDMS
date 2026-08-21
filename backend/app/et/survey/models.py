"""ET 課後問卷 model（ET_SURVEY 及其題目 / 選項 / 填答主檔 / 填答明細）。

2026-07-02 需求變更新增。問卷**具名、單選、一人一次、送出不可改**；填寫不是完課條件、
不計入學習進度。課程 `CLOSED` 期間不可填寫（已填內容可回看）。

**題目凍結**：該問卷已有任何填答時，題目與選項不可再修改（應用層檢核），僅可停用——
比快照機制更簡單，且避免已填資料與題目對不上。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtSurvey(BaseModel):
    """課後問卷（ET_SURVEY）——一門課程 0~1 份（`COURSE_ID` 唯一）。

    `IS_ACTIVE=false` 時學員端不顯示入口，已填資料保留。
    """

    __tablename__ = "ET_SURVEY"
    __table_args__ = (
        PrimaryKeyConstraint("SURVEY_ID", name="PK_ET_SURVEY"),
        UniqueConstraint("COURSE_ID", name="UQ_ET_SURVEY_COURSE"),
    )

    survey_id: Mapped[int] = mapped_column("SURVEY_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_SURVEY_COURSE"), nullable=False
    )
    survey_name: Mapped[str] = mapped_column("SURVEY_NAME", String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column("IS_ACTIVE", Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtSurveyQuestion(BaseModel):
    """問卷題目（ET_SURVEY_QUESTION）——題型一律**單選**（不設題型欄位）。

    同問卷下至少 1 題方可對學員開放。
    """

    __tablename__ = "ET_SURVEY_QUESTION"
    __table_args__ = (
        PrimaryKeyConstraint("SQ_ID", name="PK_ET_SURVEY_QUESTION"),
        UniqueConstraint("SURVEY_ID", "SORT_ORDER", name="UQ_ET_SURVEY_QUESTION_ORDER"),
    )

    sq_id: Mapped[int] = mapped_column("SQ_ID", BigInteger, Identity(), nullable=False)
    survey_id: Mapped[int] = mapped_column(
        "SURVEY_ID",
        BigInteger,
        ForeignKey("ET_SURVEY.SURVEY_ID", name="FK_ET_SURVEY_QUESTION_SURVEY"),
        nullable=False,
    )
    stem: Mapped[str] = mapped_column("STEM", String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtSurveyOption(BaseModel):
    """問卷選項（ET_SURVEY_OPTION）——如 滿意 / 普通 / 不滿意，教師自訂；同題至少 2 個。"""

    __tablename__ = "ET_SURVEY_OPTION"
    __table_args__ = (
        PrimaryKeyConstraint("SO_ID", name="PK_ET_SURVEY_OPTION"),
        UniqueConstraint("SQ_ID", "SORT_ORDER", name="UQ_ET_SURVEY_OPTION_ORDER"),
    )

    so_id: Mapped[int] = mapped_column("SO_ID", BigInteger, Identity(), nullable=False)
    sq_id: Mapped[int] = mapped_column(
        "SQ_ID",
        BigInteger,
        ForeignKey("ET_SURVEY_QUESTION.SQ_ID", name="FK_ET_SURVEY_OPTION_QUESTION"),
        nullable=False,
    )
    option_text: Mapped[str] = mapped_column("OPTION_TEXT", String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)


class EtSurveyResponseM(BaseModel):
    """問卷填答主檔（ET_SURVEY_RESPONSE_M）——**具名**、一人一次。

    `(SURVEY_ID, USER_ID)` 唯一；送出後不可修改 / 刪除，學員可回看自己填答內容。
    """

    __tablename__ = "ET_SURVEY_RESPONSE_M"
    __table_args__ = (
        PrimaryKeyConstraint("RESPONSE_ID", name="PK_ET_SURVEY_RESPONSE_M"),
        UniqueConstraint("SURVEY_ID", "USER_ID", name="UQ_ET_SURVEY_RESPONSE_SURVEY_USER"),
        Index("IX_ET_SURVEY_RESPONSE_USER", "USER_ID"),
    )

    response_id: Mapped[int] = mapped_column("RESPONSE_ID", BigInteger, Identity(), nullable=False)
    survey_id: Mapped[int] = mapped_column(
        "SURVEY_ID",
        BigInteger,
        ForeignKey("ET_SURVEY.SURVEY_ID", name="FK_ET_SURVEY_RESPONSE_SURVEY"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column("SUBMITTED_AT", DateTime(timezone=True), nullable=False)


class EtSurveyResponseD(BaseModel):
    """問卷填答明細（ET_SURVEY_RESPONSE_D）——每題一個選擇（單選）。

    統計檢視以 `SQ_ID × SO_ID` 聚合（各選項人數與百分比）。
    """

    __tablename__ = "ET_SURVEY_RESPONSE_D"
    __table_args__ = (
        PrimaryKeyConstraint("RD_ID", name="PK_ET_SURVEY_RESPONSE_D"),
        UniqueConstraint("RESPONSE_ID", "SQ_ID", name="UQ_ET_SURVEY_RESPONSE_D_RESPONSE_Q"),
    )

    rd_id: Mapped[int] = mapped_column("RD_ID", BigInteger, Identity(), nullable=False)
    response_id: Mapped[int] = mapped_column(
        "RESPONSE_ID",
        BigInteger,
        ForeignKey("ET_SURVEY_RESPONSE_M.RESPONSE_ID", name="FK_ET_SURVEY_RESPONSE_D_RESPONSE"),
        nullable=False,
    )
    sq_id: Mapped[int] = mapped_column(
        "SQ_ID",
        BigInteger,
        ForeignKey("ET_SURVEY_QUESTION.SQ_ID", name="FK_ET_SURVEY_RESPONSE_D_QUESTION"),
        nullable=False,
    )
    so_id: Mapped[int] = mapped_column(
        "SO_ID",
        BigInteger,
        ForeignKey("ET_SURVEY_OPTION.SO_ID", name="FK_ET_SURVEY_RESPONSE_D_OPTION"),
        nullable=False,
    )
