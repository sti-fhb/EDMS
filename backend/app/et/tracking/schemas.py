"""ET03 學員學習狀況追蹤之請求 / 回應 schema（US9 / #322）。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.et.attempt.schemas import QuestionResult


class EnrollmentRow(BaseModel):
    """`paginate()` 與 `StudentRow` 之間的中介——**只含 `ET_ENROLLMENT` 自身的欄位**。

    `paginate()` 以 `result.scalars()` 取結果（只拿第一欄）且必須給 schema 序列化，故
    清單查詢只能選 `EtEnrollment`；聚合值由 service 批次補齊後才組成 `StudentRow`。

    刻意**不讓 `StudentRow` 的聚合欄位帶預設值**——那樣雖能一步到位，但漏補時會靜默送出
    0（而「0 分」與「未作答」意義相反）。多一個中介型別換「少一個欄位就是 TypeError」。

    ⚠️ **不含 `completion_status`**：那個欄位是死的（只在加入時寫入 `NOT_STARTED`），
    放進來遲早有人直接用它。要的是即時計算的值，見 `StudentRow`。
    """

    model_config = {"from_attributes": True}

    user_id: str
    joined_at: datetime
    last_activity_at: datetime | None


class StudentRow(BaseModel):
    """區塊 1 的一列學員（`FR-ET-US9-02`）。

    ## `completion_status` / `progress_pct` 為**即時計算**，不讀 `ET_ENROLLMENT` 的欄位

    `ET_ENROLLMENT.COMPLETION_STATUS` 只在加入課程時寫入 `NOT_STARTED`，**沒有任何路徑
    推進它**；`COMPLETED_AT` 則全無寫入點。讀它們會讓每位學員永遠顯示「未開始」，而
    畫面上看不出資料是死的。ET04「我的課程」於 #284 踩過同一個坑並已改為即時導出
    （`enrollment/service.my_courses` 有對應註解），本頁沿用該做法。
    """

    user_id: str
    #: 取自 `DP_USER.USER_NAME`；查無（帳號已刪）時為 `None`。
    user_name: str | None
    joined_at: datetime
    #: `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED`——由完成項目數即時導出。
    completion_status: str
    #: 0~100 之整數百分比（四捨五入）。完課判定**不**看這個值，見 `is_course_completed`。
    progress_pct: int
    #: 已作答測驗之最高分平均；**完全未作答時為 `None`**（前端顯示「—」）。
    #: 回 `None` 而非 0——0 分與未作答意義相反，混為一談會讓教師誤判需要輔導的對象。
    avg_score: Decimal | None
    #: 最近一次學習動作**或測驗提交**時間（取兩者較晚者，見 service）。
    last_activity_at: datetime | None


class TeacherAttemptRow(BaseModel):
    """區塊 2：某學員於某測驗的一次作答（AC 4）。

    與學員端 `attempt/schemas.AttemptSummary` 欄位相近但**刻意分開**：教師端多一層
    「這是誰的」語境，且日後兩端的欄位需求會分岔（如教師端要加核可狀態）。共用一個
    schema 會讓其中一端的新增欄位污染另一端的回應。
    """

    attempt_id: int
    attempt_no: int
    submitted_at: datetime
    score: Decimal
    #: 該次的配分總和（快照）。少了分母時 60/100 與 60/300 在清單上都只是「60」。
    points_total: int
    is_pass: bool


class TeacherQuizRow(BaseModel):
    """區塊 2：某學員於某測驗的作答概況。

    `attempts` 為空代表**尚未作答**（ET-MSG-ET03-005）——該測驗仍要列出，否則教師
    分不出「他沒考」與「這門課沒這個測驗」。
    """

    quiz_id: int
    quiz_name: str
    max_retry: int
    #: 本輪已用次數（已扣掉先前重置的基準），供 `can_reset_retry` 判定。
    used_attempts: int
    #: 該學員於此測驗是否曾及格。
    is_passed: bool
    #: 是否可重置重考次數——**由後端判定**，前端不自行推導（規則會變，兩份遲早分岔）。
    can_reset: bool
    attempts: list[TeacherAttemptRow]


class TeacherStudentAttempts(BaseModel):
    """區塊 2 的一位學員（含其所有測驗）。"""

    user_id: str
    user_name: str | None
    quizzes: list[TeacherQuizRow]


class AttemptOverview(BaseModel):
    """區塊 2 的完整回應。

    **不分頁**：FR-ET-US9-04 明訂「一次列出所有曾作答之學員」，且此區塊為摺疊式
    （預設收合），一次載入的是摘要而非明細。
    """

    students: list[TeacherStudentAttempts]


class TeacherAttemptDetail(BaseModel):
    """區塊 2：教師端檢視某次 attempt 的逐題明細（AC 4 / FR-ET-US9-05）。

    逐題內容沿用學員端的 `QuestionResult`——**同一份資料兩端必須長得一樣**，否則教師
    與學員對著同一次作答會看到不同的對錯或得分。

    多出 `user_id` / `user_name`：教師端的語境是「這是誰的考卷」，學員端沒有這個問題。
    """

    attempt_id: int
    user_id: str
    user_name: str | None
    quiz_name: str
    attempt_no: int
    submitted_at: datetime
    score: Decimal
    points_total: int
    pass_score: int
    is_pass: bool
    questions: list[QuestionResult]
