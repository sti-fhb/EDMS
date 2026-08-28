"""ET 課後問卷之內建模板（#238）。

教師建立問卷時可套用模板取得一組現成題目，再自由編修。套用後題目即為該問卷的
一般題目，**不與模板保持任何關聯**——之後改模板不會影響已建立的問卷，改問卷也不會
回寫模板。

## 為何放後端而非前端常數

套用一個模板 = 建立 N 題 × M 選項。若由前端逐題呼叫 API，中途失敗會留下**半套用**的
問卷（例如 3 題只建了 1 題），教師得自己收拾殘局，而他甚至不知道發生了什麼。後端單一
端點在同一交易內完成，要嘛全成要嘛全不成。

## 為何不建表

比照 `data-model.md` §Lookup 代碼定義之「不建表」定案：本專案無 lookup 表機制，
少量、變動不頻繁的定義一律以模組層常數表達。模板若日後需要由管理者維護，再考慮
升格為 `DP_PARAM` 或獨立資料表。

## 不可變

`SURVEY_TEMPLATES` 是模組層常數、跨請求共用。若可變，某次套用不小心改到它，
之後每位教師拿到的都是被改過的內容，而且改動不落任何紀錄。故一律 frozen dataclass
+ `tuple`，讓誤改在第一次就爆出來。
"""

from dataclasses import dataclass
from typing import Final

from app.core.exceptions import AppError
from app.et.constants import SURVEY_QUESTION_SINGLE, SURVEY_QUESTION_TEXT


@dataclass(frozen=True)
class TemplateQuestion:
    """模板中的一題。

    `options` 對問答題恆為空 tuple——與 `rules.ensure_options_match_type` 同一約束，
    測試以該規則反過來驗模板內容，兩邊不會漂移。
    """

    question_type: str
    stem: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyTemplate:
    """一組模板。"""

    code: str
    name: str
    description: str
    questions: tuple[TemplateQuestion, ...]


@dataclass(frozen=True)
class TemplateSummary:
    """模板清單列（回應）——**不含題目內容**。

    教師選模板時看的是名稱與題數；把整包題目塞進清單會讓回應隨模板數量膨脹，
    而那些內容在他選定之前都用不到。
    """

    code: str
    name: str
    description: str
    question_count: int


SURVEY_TEMPLATES: Final[tuple[SurveyTemplate, ...]] = (
    SurveyTemplate(
        code="SATISFACTION",
        name="課程滿意度",
        description="整體內容、教材難易度與時間安排之滿意度回饋",
        questions=(
            TemplateQuestion(
                question_type=SURVEY_QUESTION_SINGLE,
                stem="您對本課程整體內容是否滿意？",
                options=("滿意", "普通", "不滿意"),
            ),
            TemplateQuestion(
                question_type=SURVEY_QUESTION_SINGLE,
                stem="課程教材的難易度是否合適？",
                options=("合適", "太難", "太簡單"),
            ),
            TemplateQuestion(
                question_type=SURVEY_QUESTION_SINGLE,
                stem="課程時間安排是否恰當？",
                options=("恰當", "太長", "太短"),
            ),
        ),
    ),
    SurveyTemplate(
        code="EFFECTIVENESS",
        name="學習成效回饋",
        description="課程對實際工作之幫助與推薦意願，含一題開放式建議",
        questions=(
            TemplateQuestion(
                question_type=SURVEY_QUESTION_SINGLE,
                stem="本課程對您的實際工作是否有幫助？",
                options=("很有幫助", "有一些幫助", "沒有幫助"),
            ),
            TemplateQuestion(
                question_type=SURVEY_QUESTION_SINGLE,
                stem="您是否會推薦同仁參加本課程？",
                options=("會", "不會"),
            ),
            # 刻意放一題問答——讓模板本身就是問答題型的示範，教師套用後立刻看得到
            # 兩種題型長什麼樣，不必自己摸索「問答題要怎麼建」。
            TemplateQuestion(
                question_type=SURVEY_QUESTION_TEXT,
                stem="對本課程還有什麼建議？",
            ),
        ),
    ),
)

_NOT_FOUND = AppError(status_code=404, detail="查無此問卷模板", error_code="ET_SURVEY_009")


def list_templates() -> list[TemplateSummary]:
    """模板清單（不含題目內容）。"""
    return [
        TemplateSummary(
            code=t.code,
            name=t.name,
            description=t.description,
            question_count=len(t.questions),
        )
        for t in SURVEY_TEMPLATES
    ]


def get_template(code: str) -> SurveyTemplate:
    """依代碼取模板。

    Raises:
        AppError: 404 `ET_SURVEY_009`，查無此模板。
    """
    for template in SURVEY_TEMPLATES:
        if template.code == code:
            return template
    raise _NOT_FOUND
