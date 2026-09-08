"""ET05 課後問卷填寫（US13 / #284）schema——學員端。

## 不與教師端 `survey/schemas.py` 共用

教師端的 `SurveyDetail` 含 `version`（樂觀鎖）、`frozen`、`responded_count` /
`not_responded_count` 等編輯與統計用欄位。共用會把「已填 N 人 / 未填 M 人」發給每一位
學員——那是教師追蹤學員狀況才該看見的資訊（屬 US9），而學員只需要題目與自己的作答。

同一個理由見 `learning/schemas.py`（學員端教材回應不含 `file_path`）。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.et.survey_fill.rules import ANSWER_TEXT_MAX_LEN

#: 單次送出之題數上限（**請求大小防護，非業務規則**）。
#:
#: 業務判定在 `rules.validate_answers`（逐題比對題目清單，多送 / 少送都擋）。這裡放寬
#: 到 200 只是不讓單一請求塞進上萬列——問卷實務上不會超過數十題，而 `data-model` 未訂
#: 題數上限，故不能拿它當業務界限。同 `enrollment/schemas.INVITATION_CODE_INPUT_MAX_LEN`
#: 之取捨。
MAX_ANSWERS_PER_REQUEST = 200


class SurveyEntry(BaseModel):
    """ET05 側欄之課後問卷入口狀態（AC 1 / AC 2 / AC 10 / AC 11）。

    隨 `GET /courses/{id}/learn` 一併回傳，**不另開端點**：側欄必須在第一次繪製就決定
    「渲染入口 / 不渲染」，二次請求會造成可見的跳動，而「未完課 → 不顯示」是最常見的
    狀態，為它多打一趟請求不划算。

    Attributes:
        state: `HIDDEN` / `FILLABLE` / `SUBMITTED` / `COURSE_CLOSED`（見
            `rules.ALL_ENTRY_STATES`）。前端以此單一欄位分支，不用布林旗標的組合——
            那會產生不可能的狀態，且每種組合都得寫一條分支。
        submitted_at: 自己的送出時間；`state != SUBMITTED` 時為 `None`。唯讀回看時
            顯示「您已於 X 送出」——「我什麼時候填的」是自然的疑問。
    """

    survey_id: int
    survey_name: str
    state: str
    submitted_at: datetime | None


class SurveyOptionRow(BaseModel):
    """單選題之一個選項。**不含 `sort_order`**——已依序排好，前端照著渲染即可。"""

    so_id: int
    option_text: str


class SurveyQuestionRow(BaseModel):
    """問卷題目。

    Attributes:
        question_type: `SINGLE`（單選，必答）/ `TEXT`（問答，**選填**）。前端據此決定
            渲染 `RadioGroup` 或 `TextField`，以及題幹後面要不要標必填星號。
        options: 問答題恆為空陣列（`ET_SURVEY_008`：問答題不可設定選項）。
    """

    sq_id: int
    question_type: str
    stem: str
    options: list[SurveyOptionRow]


class SurveyAnswerRow(BaseModel):
    """自己的一題填答（唯讀回看）。

    **留空的問答題不會出現在此清單**（SA Q1 裁示 A：`_D` 只記錄實際有作答的題目），
    前端據此把該題呈現為「未填」。
    """

    sq_id: int
    so_id: int | None
    answer_text: str | None


class SurveyForm(BaseModel):
    """問卷填寫頁所需之一切（AC 3 / AC 9 / AC 10）。

    填寫態、唯讀回看態、課程已關閉態三者共用同一個回應形狀，由 `state` 分支——
    三種狀態下前端要顯示的**題目是同一份**，差別只在能不能改與有沒有送出鈕。
    """

    survey_id: int
    survey_name: str
    state: str
    submitted_at: datetime | None
    questions: list[SurveyQuestionRow]
    my_answers: list[SurveyAnswerRow]


class SurveyAnswerIn(BaseModel):
    """送出之單題作答。

    `so_id` 與 `answer_text` 皆為選填**在 schema 層**——互斥與必填由
    `rules.validate_answers` 依題型判定。放在 schema 會需要兩個不同的請求型別，而
    前端送出的是一份混合題型的清單。
    """

    sq_id: int = Field(ge=1)
    so_id: int | None = Field(default=None, ge=1)
    answer_text: str | None = Field(default=None, max_length=ANSWER_TEXT_MAX_LEN)


class SurveySubmitReq(BaseModel):
    """送出問卷（AC 7）。

    `answers` 可為空陣列——一份全是問答題且全部留空的問卷是合法的送出（FR-03）。
    """

    answers: list[SurveyAnswerIn] = Field(default_factory=list, max_length=MAX_ANSWERS_PER_REQUEST)


class SurveySubmitResult(BaseModel):
    """送出結果（ET-MSG-ET05-102）。"""

    response_id: int
    submitted_at: datetime
