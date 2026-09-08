"""ET06 測驗作答（US6 / #279）schema。

## 作答中**絕不**回傳 `is_correct`

`QuestionForAnswering` 的選項只有 `option_id` 與 `text`。正確答案存在於
`OPTIONS_SNAPSHOT`，但**只在提交後的明細（`QuestionResult`）才送給前端**——作答中送出
等於把答案印在網頁原始碼裡，而 wireframe 的洗牌設計正是為了讓答案不可預測。

兩個 schema 的形狀差異就是這條規則的體現，故**刻意不共用基底**：共用之後只要有人為了
少寫幾行把 `is_correct` 提到共同欄位，作答中就會跟著漏出去，而畫面上完全看不出來。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

#: 單題可選的選項數上限（`data-model`：同題目下選項 2–6 個）。
#:
#: 這是**請求大小防護**——正常的多選題最多勾 6 個，收到上百個代表不是正常操作。
MAX_SELECTED_OPTIONS = 6


class OptionForAnswering(BaseModel):
    """作答中呈現的選項。**沒有 `is_correct`**（見模組 docstring）。"""

    option_id: int
    text: str


class QuestionForAnswering(BaseModel):
    """作答中呈現的題目，依該次 attempt 的順序快照排列。"""

    question_id: int
    question_type: str
    stem: str
    points: int
    options: list[OptionForAnswering]
    #: 已暫存的作答；空清單 = 未作答（供左側導覽列的「已答 / 未答」三態）。
    selected_options: list[int]


class AttemptState(BaseModel):
    """作答中的完整狀態（開始作答與續作共用同一個形狀）。

    Attributes:
        remaining_sec: 剩餘秒數，由後端自 `STARTED_AT` 推導。**`None` = 不限時**，
            前端據此不顯示倒數區塊——不可當成 0（那會渲染成「時間到」）。
        resumed: 本次回傳的是既有的進行中作答，而非新建（#279 SA Q1 裁示 A）。
            前端據此提示「已回到未完成的作答」，避免學員以為自己按了兩次。
    """

    attempt_id: int
    quiz_id: int
    quiz_name: str
    attempt_no: int
    #: 目前狀態。前端據此在「已提交後又用上一頁回到作答頁」時導向結果頁，
    #: 而不是讓學員對著一份其實已經交出去的考卷繼續作答。
    status: str
    pass_score: int
    time_limit_min: int | None
    remaining_sec: int | None
    resumed: bool
    questions: list[QuestionForAnswering]


class AnswerReq(BaseModel):
    """暫存單題作答。

    空清單為合法輸入——學員可以取消勾選（多選）或清掉答案，那與「從未作答」等價。
    """

    #: 元素亦加界限：計分面不可利用（外來 id 只會落進「誤選」使分數下降），但不設界的話
    #: 任意整數會被原樣寫進 `SELECTED_OPTIONS`。比照 `course/schemas.py` 對 `tag_id` 的作法。
    selected_options: list[int] = Field(
        default_factory=list, max_length=MAX_SELECTED_OPTIONS, json_schema_extra={"items": {"minimum": 1}}
    )


class OptionResult(BaseModel):
    """明細中的選項：**此時才帶 `is_correct`**（AC 11 強制顯示正確答案）。"""

    option_id: int
    text: str
    is_correct: bool
    selected: bool


class QuestionResult(BaseModel):
    """逐題明細（依該次 attempt 的快照渲染）。

    Attributes:
        outcome: `CORRECT` / `PARTIAL` / `WRONG`——由**後端**判定。前端若自行以
            「得分 == 配分」推導，會把「多選全對」與「單選答對」以外的情形算錯
            （例如配分 0 的題目）。
    """

    question_id: int
    question_type: str
    stem: str
    points: int
    score: Decimal
    outcome: str
    options: list[OptionResult]


class AttemptResult(BaseModel):
    """提交後的閱卷結果（AC 7）。"""

    attempt_id: int
    #: 供結果頁的「重新作答」導回引導頁。少了它前端只能從 `attempt_id` 猜，而那會導到
    #: 錯的測驗——`attempt_id` 與 `quiz_id` 是兩個獨立的序列。
    quiz_id: int
    attempt_no: int
    status: str
    score: Decimal
    #: 本次 attempt 的配分總和（快照）。**前端的分母用它、不可寫死 100**——「總和 = 100」
    #: 只在課程發布當下檢核，發布後教師仍可改配分或增刪題目。
    points_total: int
    pass_score: int
    is_pass: bool
    submitted_at: datetime
    #: 提交後剩餘的可作答次數；> 0 且未及格時前端顯示「重新作答」。
    remaining_attempts: int
    questions: list[QuestionResult]


class QuizIntro(BaseModel):
    """引導頁（AC 1 / AC 2）。

    Attributes:
        time_limit_min: `None` = 不限時。前端須顯示「不限時」而**不是「0 分」**。
        can_start: 是否可開始作答；`False` 時前端禁用按鈕並顯示 ET-MSG-ET06-001。
        last_score: **最近一次**的成績。與 `best_score` 一起給——結業成績取最高分，
            只顯示其一都會誤導（只給最近一次會讓學員以為自己退步了）。
        in_progress_attempt_id: 有未完成的作答時帶其 id，前端把按鈕改為「繼續作答」。
    """

    quiz_id: int
    quiz_name: str
    description: str | None
    question_count: int
    pass_score: int
    time_limit_min: int | None
    max_retry: int
    remaining_attempts: int
    can_start: bool
    last_score: Decimal | None
    best_score: Decimal | None
    is_passed: bool
    in_progress_attempt_id: int | None
