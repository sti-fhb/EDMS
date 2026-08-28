"""ET 課後問卷（US3 / #204）schema。

長度上限對齊 `data-model.md` §ET_SURVEY*；業務規則（選項數下限、凍結）進 `rules.py`。

## 與測驗題目 schema 的差異

- **`question_type` 值域不同**：問卷為 `SINGLE` / `TEXT`，測驗為 `SINGLE` / `MULTIPLE`
- **無 `is_correct`**：問卷收集意見，沒有對錯
- **無 `points`**：問卷不計分、不計入學習進度
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# `SURVEY_NAME` VARCHAR(100)、`STEM` VARCHAR(500)、`OPTION_TEXT` VARCHAR(200)。
SURVEY_NAME_MAX_LEN = 100
STEM_MAX_LEN = 500
OPTION_TEXT_MAX_LEN = 200

#: 每題選項數之**請求大小防護**，非業務規則。
#:
#: `data-model` §ET_SURVEY_OPTION 只訂下限 2、未訂上限（與測驗題目的 2–6 不同）。
#: 這裡設一個寬鬆界限純粹是不讓單一請求塞進上萬個選項；真正的業務判定在
#: `rules.ensure_option_count_valid`，兩者錯誤碼與訊息不同。
MAX_OPTIONS_PER_QUESTION = 20

#: 一份問卷之題數上限。重排送完整陣列，無界限會成為放大面（比照章節 / 項目 / 測驗題目）。
MAX_QUESTION_IDS = 500


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name}不得為空白")
    return stripped


class SurveyCreateReq(BaseModel):
    """建立問卷（掛課程層級，不掛章節）。

    建立時**不帶題目**——教師是先建問卷再逐題新增的，比照測驗的空殼流程。
    """

    survey_name: str = Field(min_length=1, max_length=SURVEY_NAME_MAX_LEN)

    @field_validator("survey_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        return _strip_required(v, "問卷名稱")


class SurveyUpdateReq(SurveyCreateReq):
    """更新問卷名稱與啟用狀態（帶問卷自身之 `version`）。

    **本請求不受凍結限制**：AC 21 明訂已有填答時教師「僅可停用問卷」——若連停用都
    擋掉，凍結後整張卡片就變成死的，教師無路可走。
    """

    is_active: bool
    version: int = Field(ge=0)


class SurveyOptionInput(BaseModel):
    """問卷選項（請求）。順序即陣列順序，不另帶 `sort_order`。"""

    option_text: str = Field(min_length=1, max_length=OPTION_TEXT_MAX_LEN)

    @field_validator("option_text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        return _strip_required(v, "選項文字")


class SurveyQuestionCreateReq(BaseModel):
    """新增問卷題目（含其全部選項），追加至最末。

    選項與題目**同一個請求**：沒有選項的單選題不是有效題目，拆成兩次請求會讓中途失敗
    留下無選項的題目，而那正是 `ET_SURVEY_004` 要擋的狀態。

    **問答題（`TEXT`）之 `options` 須為空陣列**——帶了就 422 `ET_SURVEY_008`。
    這裡刻意不在 schema 層擋（`Literal` 管不到跨欄位條件），交給
    `rules.ensure_options_match_type`，讓兩種違規有各自的錯誤碼與訊息。
    """

    question_type: Literal["SINGLE", "TEXT"]
    stem: str = Field(min_length=1, max_length=STEM_MAX_LEN)
    options: list[SurveyOptionInput] = Field(default_factory=list, max_length=MAX_OPTIONS_PER_QUESTION)

    @field_validator("stem")
    @classmethod
    def _stem_not_blank(cls, v: str) -> str:
        return _strip_required(v, "題幹")


class SurveyQuestionUpdateReq(SurveyQuestionCreateReq):
    """更新題目與其選項（全量覆寫；帶題目自身之 `version`）。"""

    version: int = Field(ge=0)


class SurveyQuestionReorderReq(BaseModel):
    """題目重排（送完整順序陣列；帶**問卷層** `version`）。

    問卷題目**保留教師排序**（SA 裁示）——與測驗題目不同，問卷不洗牌。
    """

    question_ids: list[int] = Field(max_length=MAX_QUESTION_IDS)
    version: int = Field(ge=0)


class SurveyOptionRow(BaseModel):
    """選項列（回應）。"""

    model_config = {"from_attributes": True}

    so_id: int
    option_text: str
    sort_order: int


class SurveyQuestionRow(BaseModel):
    """題目列（回應，含選項）。問答題之 `options` 恆為空陣列。"""

    sq_id: int
    question_type: str
    stem: str
    sort_order: int
    version: int
    options: list[SurveyOptionRow]


class SurveyDetail(BaseModel):
    """問卷詳細（回應）。

    `frozen` 由後端判定並回傳，前端不自行從 `responded_count` 推導——凍結的定義是
    「存在任何未刪除之填答」，讓兩邊各算一次遲早會漂移。
    """

    survey_id: int
    course_id: int
    survey_name: str
    is_active: bool
    version: int
    #: 已有任何填答 → 題目與選項凍結（AC 21）。
    frozen: bool
    #: 已填人數（= 未刪除之 `ET_SURVEY_RESPONSE_M` 筆數）。
    responded_count: int
    #: 未填人數（= 該課程已加入學員數 − 已填人數，下限 0）。
    pending_count: int
    questions: list[SurveyQuestionRow]


class SurveyTemplateRow(BaseModel):
    """模板清單列（回應）——**不含題目內容**。

    教師選模板時看的是名稱與題數；把整包題目塞進清單會讓回應隨模板數量膨脹，
    而那些內容在他選定之前都用不到。
    """

    model_config = {"from_attributes": True}

    code: str
    name: str
    description: str
    question_count: int


class ApplyTemplateReq(BaseModel):
    """套用模板（帶問卷層 `version`）。

    僅於問卷 **0 題**時可套用（否則 409 `ET_SURVEY_010`）——避免模板題目與教師已建的
    題目混在一起、順序難以預期。
    """

    template_code: str = Field(min_length=1, max_length=50)
    version: int = Field(ge=0)
