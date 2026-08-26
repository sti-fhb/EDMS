"""ET 測驗設定與題目（US3 / #203）schema。

數值範圍在此以 `Field` 約束，不重複寫進 `rules.py`——pydantic 於請求解析階段就擋下，
走到 service 時必然合法。業務規則（選項數、正確選項數符題型）才進 rules。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# `QUIZ_NAME` 為 VARCHAR(100)、`STEM` 為 VARCHAR(500)、`OPTION_TEXT` 為 VARCHAR(200)。
QUIZ_NAME_MAX_LEN = 100
STEM_MAX_LEN = 500
OPTION_TEXT_MAX_LEN = 200
# 測驗說明為 TEXT（SA 裁示 #203 Q1），比照教材說明給一個應用層界限。
QUIZ_DESCRIPTION_MAX_LEN = 5_000
# 每題選項數上限（data-model §ET_OPTION）。schema 先擋一次，rules 再擋一次——
# schema 擋的是「請求格式」，rules 擋的是「業務規則」，兩者訊息與錯誤碼不同。
MAX_OPTIONS_PER_QUESTION = 6
# 一份測驗之題數上限。重排送完整陣列，無界限會成為放大面（比照章節 / 項目）。
MAX_QUESTION_IDS = 500


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name}不得為空白")
    return stripped


class QuizUpdateReq(BaseModel):
    """更新測驗設定（帶測驗自身之 `version`）。

    **不含題目**——題目各有自己的端點與 `VERSION`。把題目塞進同一個 PUT 會讓「改個
    及格分數」也得把整份題庫重送，且與 FR-ET-US3-15「不同實體並行編輯互不衝突」相衝。
    """

    quiz_name: str = Field(min_length=1, max_length=QUIZ_NAME_MAX_LEN)
    #: 測驗說明——**純文字**（SA 裁示 #203 Q1），不經 WYSIWYG、不走 HTML 消毒。
    description: str | None = Field(default=None, max_length=QUIZ_DESCRIPTION_MAX_LEN)
    pass_score: int = Field(ge=0, le=100)
    #: `None` = 不限時；`>= 1` = 限時 N 分鐘（data-model 之兩態語意）。
    time_limit_min: int | None = Field(default=None, ge=1)
    max_retry: int = Field(ge=0, le=999)
    version: int = Field(ge=0)

    @field_validator("quiz_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        return _strip_required(v, "測驗名稱")

    @field_validator("description")
    @classmethod
    def _description_blank_is_none(cls, v: str | None) -> str | None:
        """全空白視同未填——避免「有說明但顯示空白」與「沒有說明」在下游難以區辨。"""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class OptionInput(BaseModel):
    """題目選項（請求）。順序即陣列順序，不另帶 `sort_order`。"""

    option_text: str = Field(min_length=1, max_length=OPTION_TEXT_MAX_LEN)
    is_correct: bool = False

    @field_validator("option_text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        return _strip_required(v, "選項文字")


class QuestionCreateReq(BaseModel):
    """新增題目（含其全部選項），追加至測驗最末。

    選項與題目**同一個請求**：一個沒有選項的題目不是有效題目，拆成兩次請求會讓
    中途失敗留下無選項的題目，而那正是 `ET_QUESTION_003` 要擋的狀態。
    """

    question_type: Literal["SINGLE", "MULTIPLE"]
    stem: str = Field(min_length=1, max_length=STEM_MAX_LEN)
    points: int = Field(ge=0, le=100)
    options: list[OptionInput] = Field(max_length=MAX_OPTIONS_PER_QUESTION)

    @field_validator("stem")
    @classmethod
    def _stem_not_blank(cls, v: str) -> str:
        return _strip_required(v, "題幹")


class QuestionUpdateReq(QuestionCreateReq):
    """更新題目與其選項（全量覆寫；帶題目自身之 `version`）。

    選項採**全量覆寫**而非逐項增刪：選項沒有獨立的識別需求（作答紀錄以 snapshot
    保存當時的選項內容，不以 `OPTION_ID` 外鍵關聯），逐項 diff 只是徒增複雜度。
    """

    version: int = Field(ge=0)


class QuestionReorderReq(BaseModel):
    """題目重排（送完整順序陣列；帶**測驗層** `version`）。

    這是教師端的排序。學員作答時的順序由系統洗牌並凍結於 attempt 快照（屬 #6）。
    """

    question_ids: list[int] = Field(max_length=MAX_QUESTION_IDS)
    version: int = Field(ge=0)


class OptionRow(BaseModel):
    """選項列（回應）。"""

    model_config = {"from_attributes": True}

    option_id: int
    option_text: str
    is_correct: bool
    sort_order: int


class QuestionRow(BaseModel):
    """題目列（回應，含選項）。"""

    question_id: int
    question_type: str
    stem: str
    points: int
    sort_order: int
    version: int
    options: list[OptionRow]


class QuizDetail(BaseModel):
    """測驗詳細（回應）。

    `points_total` 由後端算出——AC 要求 UI 常駐顯示配分總和（如「90 / 100」），
    讓前端自己加總會在題目分頁載入時算錯。**總和 ≠ 100 不在此阻擋**：教師逐題新增
    時總和必然一度不等於 100，阻擋發布是 #204 的事（FR-ET-US3-11）。
    """

    quiz_id: int
    quiz_name: str
    description: str | None
    pass_score: int
    time_limit_min: int | None
    max_retry: int
    version: int
    questions: list[QuestionRow]
    points_total: int
