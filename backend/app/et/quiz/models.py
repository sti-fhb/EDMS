"""ET 測驗 model（ET_QUIZ / ET_QUESTION / ET_OPTION / 作答主檔+明細 / 重考重置）。

**Attempt Snapshot**：`ET_QUIZ_ATTEMPT_M` 於 `STARTED_AT` 凍結題目順序 / 選項順序 /
及格分數 / 時間限制，`ET_QUIZ_ATTEMPT_D` 逐題凍結題幹 / 配分 / 題型 / 選項——
學員作答中教師修改測驗不影響當前 attempt，避免吞分爭議。

**重考次數語意**（2026-08-19 #179 定案）：attempt **永不刪除**（append-only 語意，
`ATTEMPT_NO` 標次序）；「重置重考次數」以 `ET_QUIZ_RETRY_RESET` 記下當下 attempt 數
為基準——原「歸 0」若以刪除 attempt 實作，將與「歷次作答明細永久可回看」互斥。
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import AuditLogBaseModel, BaseModel


class EtQuiz(BaseModel):
    """測驗主檔（ET_QUIZ）。

    `TIME_LIMIT_MIN`：**NULL = 不限時**、`>= 1` = 限時 N 分鐘（倒數歸零自動提交）。
    `MAX_RETRY`：**0 = 不允許重考**（僅可作答 1 次）；故總可作答次數 = `MAX_RETRY + 1`。
    該測驗下各題配分總和須 = 100（發布前由應用層檢核）。
    `DESCRIPTION` 為純文字說明，顯示於學員作答開始前。
    """

    __tablename__ = "ET_QUIZ"
    __table_args__ = (PrimaryKeyConstraint("QUIZ_ID", name="PK_ET_QUIZ"),)

    quiz_id: Mapped[int] = mapped_column("QUIZ_ID", BigInteger, Identity(), nullable=False)
    quiz_name: Mapped[str] = mapped_column("QUIZ_NAME", String(100), nullable=False)
    #: 測驗說明（顯示於學員作答開始前）。**純文字**——與 `ET_MATERIAL.DESCRIPTION_HTML`
    #: 不同，不經 WYSIWYG、不走 HTML 消毒，前端須以純文字渲染（SA 裁示 #203 Q1）。
    description: Mapped[Optional[str]] = mapped_column("DESCRIPTION", Text, nullable=True)
    pass_score: Mapped[int] = mapped_column("PASS_SCORE", Integer, nullable=False, default=80)
    time_limit_min: Mapped[Optional[int]] = mapped_column("TIME_LIMIT_MIN", Integer, nullable=True)
    max_retry: Mapped[int] = mapped_column("MAX_RETRY", Integer, nullable=False, default=3)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtQuestion(BaseModel):
    """題目（ET_QUESTION）。

    多選題建立時強制至少 1 個正確選項（避免部分計分公式分母為 0）。
    `SORT_ORDER` 供教師拖拉調整；**學員端洗牌不依此**（順序存於 attempt 快照）。
    刪除採軟刪除；學員於該題之 `ET_QUIZ_ATTEMPT_D` **亦連帶軟刪除**（`DELETED=1`；
    2026-08-24 #202 變更，原為 hard delete）。成績查詢務必排除 `DELETED = 1`。
    """

    __tablename__ = "ET_QUESTION"
    __table_args__ = (
        PrimaryKeyConstraint("QUESTION_ID", name="PK_ET_QUESTION"),
        Index("IX_ET_QUESTION_QUIZ", "QUIZ_ID"),
    )

    question_id: Mapped[int] = mapped_column("QUESTION_ID", BigInteger, Identity(), nullable=False)
    quiz_id: Mapped[int] = mapped_column(
        "QUIZ_ID", BigInteger, ForeignKey("ET_QUIZ.QUIZ_ID", name="FK_ET_QUESTION_QUIZ"), nullable=False
    )
    question_type: Mapped[str] = mapped_column("QUESTION_TYPE", String(20), nullable=False)
    stem: Mapped[str] = mapped_column("STEM", String(500), nullable=False)
    points: Mapped[int] = mapped_column("POINTS", Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)
    version: Mapped[int] = mapped_column("VERSION", Integer, nullable=False, default=0)


class EtOption(BaseModel):
    """選項（ET_OPTION）——同題 2~6 個（應用層檢核）。"""

    __tablename__ = "ET_OPTION"
    __table_args__ = (
        PrimaryKeyConstraint("OPTION_ID", name="PK_ET_OPTION"),
        Index("IX_ET_OPTION_QUESTION", "QUESTION_ID"),
    )

    option_id: Mapped[int] = mapped_column("OPTION_ID", BigInteger, Identity(), nullable=False)
    question_id: Mapped[int] = mapped_column(
        "QUESTION_ID",
        BigInteger,
        ForeignKey("ET_QUESTION.QUESTION_ID", name="FK_ET_OPTION_QUESTION"),
        nullable=False,
    )
    option_text: Mapped[str] = mapped_column("OPTION_TEXT", String(200), nullable=False)
    is_correct: Mapped[bool] = mapped_column("IS_CORRECT", Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column("SORT_ORDER", Integer, nullable=False)


class EtQuizAttemptM(BaseModel):
    """測驗作答主檔（ET_QUIZ_ATTEMPT_M）——一次作答嘗試。

    `ATTEMPT_NO` 由該學員於該測驗之現有 attempt 數 + 1 產生，**不因重置重考次數而歸零**
    （歷次 attempt 永久保留可回看，per FR-ET-US9-05）。本表不因重置而刪除任何列。

    `TIME_LIMIT_SNAPSHOT` **可為 NULL**——對應 `ET_QUIZ.TIME_LIMIT_MIN` 之「NULL = 不限時」
    語意。（data-model 該欄標「必填」，但不限時的測驗無值可凍結，故此處採 nullable；
    已回報 SA 於文件同步。）
    """

    __tablename__ = "ET_QUIZ_ATTEMPT_M"
    __table_args__ = (
        PrimaryKeyConstraint("ATTEMPT_ID", name="PK_ET_QUIZ_ATTEMPT_M"),
        UniqueConstraint("USER_ID", "QUIZ_ID", "ATTEMPT_NO", name="UQ_ET_ATTEMPT_USER_QUIZ_NO"),
        Index("IX_ET_ATTEMPT_USER_QUIZ", "USER_ID", "QUIZ_ID"),
        Index("IX_ET_ATTEMPT_COURSE", "COURSE_ID"),
    )

    attempt_id: Mapped[int] = mapped_column("ATTEMPT_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_ATTEMPT_COURSE"), nullable=False
    )
    quiz_id: Mapped[int] = mapped_column(
        "QUIZ_ID", BigInteger, ForeignKey("ET_QUIZ.QUIZ_ID", name="FK_ET_ATTEMPT_QUIZ"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column("ATTEMPT_NO", Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column("STARTED_AT", DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column("SUBMITTED_AT", DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", String(20), nullable=False)
    score: Mapped[Optional[Decimal]] = mapped_column("SCORE", Numeric(5, 2), nullable=True)
    is_pass: Mapped[Optional[bool]] = mapped_column("IS_PASS", Boolean, nullable=True)
    question_order: Mapped[str] = mapped_column("QUESTION_ORDER", Text, nullable=False)
    option_order: Mapped[str] = mapped_column("OPTION_ORDER", Text, nullable=False)
    pass_score_snapshot: Mapped[int] = mapped_column("PASS_SCORE_SNAPSHOT", Integer, nullable=False)
    time_limit_snapshot: Mapped[Optional[int]] = mapped_column("TIME_LIMIT_SNAPSHOT", Integer, nullable=True)


class EtQuizAttemptD(BaseModel):
    """作答明細（ET_QUIZ_ATTEMPT_D）——某次 attempt 之各題作答與得分。

    多選題部分計分：`SCORE = max(0, (對 − 誤) ÷ 應選 × POINTS_SNAPSHOT)`，
    依 `OPTIONS_SNAPSHOT` 之 `is_correct` 計算；完全未作答之多選題視為 0 分。
    """

    __tablename__ = "ET_QUIZ_ATTEMPT_D"
    __table_args__ = (
        PrimaryKeyConstraint("DETAIL_ID", name="PK_ET_QUIZ_ATTEMPT_D"),
        UniqueConstraint("ATTEMPT_ID", "QUESTION_ID", name="UQ_ET_ATTEMPT_D_ATTEMPT_QUESTION"),
    )

    detail_id: Mapped[int] = mapped_column("DETAIL_ID", BigInteger, Identity(), nullable=False)
    attempt_id: Mapped[int] = mapped_column(
        "ATTEMPT_ID",
        BigInteger,
        ForeignKey("ET_QUIZ_ATTEMPT_M.ATTEMPT_ID", name="FK_ET_ATTEMPT_D_ATTEMPT"),
        nullable=False,
    )
    question_id: Mapped[int] = mapped_column(
        "QUESTION_ID",
        BigInteger,
        ForeignKey("ET_QUESTION.QUESTION_ID", name="FK_ET_ATTEMPT_D_QUESTION"),
        nullable=False,
    )
    stem_snapshot: Mapped[str] = mapped_column("STEM_SNAPSHOT", String(500), nullable=False)
    points_snapshot: Mapped[int] = mapped_column("POINTS_SNAPSHOT", Integer, nullable=False)
    type_snapshot: Mapped[str] = mapped_column("TYPE_SNAPSHOT", String(20), nullable=False)
    options_snapshot: Mapped[str] = mapped_column("OPTIONS_SNAPSHOT", Text, nullable=False)
    selected_options: Mapped[Optional[str]] = mapped_column("SELECTED_OPTIONS", Text, nullable=True)
    score: Mapped[Optional[Decimal]] = mapped_column("SCORE", Numeric(5, 2), nullable=True)


class EtQuizRetryReset(AuditLogBaseModel):
    """重考次數重置紀錄（ET_QUIZ_RETRY_RESET，2026-08-19 新增；append-only、僅 CREATED_*）。

    每次重置 INSERT 一列、不可修改 / 刪除（稽核完整性，比照 `ET_OWNER_TRANSFER`）；
    同一學員同一測驗可重置多次。

    **已用重考次數之計算**（取代原「歸 0」之刪除語意）：
      total = COUNT(該學員該測驗之 ET_QUIZ_ATTEMPT_M)
      base  = MAX(ATTEMPT_COUNT_AT_RESET)，無重置紀錄時為 0
      本輪已用作答次數 = total − base
      已用重考次數 = max(0, total − base − 1)   # 首次作答不計入重考
    """

    __tablename__ = "ET_QUIZ_RETRY_RESET"
    __table_args__ = (
        PrimaryKeyConstraint("RESET_ID", name="PK_ET_QUIZ_RETRY_RESET"),
        Index("IX_ET_RETRY_RESET_USER_QUIZ", "USER_ID", "QUIZ_ID"),
    )

    reset_id: Mapped[int] = mapped_column("RESET_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    quiz_id: Mapped[int] = mapped_column(
        "QUIZ_ID", BigInteger, ForeignKey("ET_QUIZ.QUIZ_ID", name="FK_ET_RETRY_RESET_QUIZ"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_RETRY_RESET_COURSE"), nullable=False
    )
    attempt_count_at_reset: Mapped[int] = mapped_column("ATTEMPT_COUNT_AT_RESET", Integer, nullable=False)
    executed_by: Mapped[str] = mapped_column("EXECUTED_BY", String(20), nullable=False)
    executed_at: Mapped[datetime] = mapped_column("EXECUTED_AT", DateTime(timezone=True), nullable=False)
