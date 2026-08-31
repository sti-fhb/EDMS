"""ET 課後問卷之內建模板（#238）。

模板是純資料 + 純函式，不需 DB——放後端而非前端常數的理由見
`app/et/survey/templates.py` 模組 docstring。
"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import ALL_SURVEY_QUESTION_TYPES, SURVEY_QUESTION_SINGLE, SURVEY_QUESTION_TEXT
from app.et.survey.rules import MIN_OPTIONS, ensure_options_match_type
from app.et.survey.templates import SURVEY_TEMPLATES, get_template, list_templates

pytestmark = pytest.mark.unit


class TestTemplateCatalog:
    def test_至少一組模板(self) -> None:
        """2026-08-31 實測回饋：由兩組合併為單一組 6 題。

        原 AC 8 寫「至少 2 組」，回饋後改為一顆「套用模板」——教師不必先決定用哪組。
        """
        assert len(SURVEY_TEMPLATES) >= 1

    def test_預設模板為六題(self) -> None:
        """六題涵蓋滿意度 / 難易度 / 時間 / 實用性 / 推薦意願 / 開放式建議。"""
        assert len(get_template("DEFAULT").questions) == 6

    def test_模板代碼唯一(self) -> None:
        codes = [t.code for t in SURVEY_TEMPLATES]
        assert len(codes) == len(set(codes))

    def test_每組模板都有題目(self) -> None:
        """0 題的模板套用後等於什麼都沒做，且會直接違反發布檢核「有問卷則至少 1 題」。"""
        for template in SURVEY_TEMPLATES:
            assert template.questions, template.code

    def test_列出模板不含題目內容(self) -> None:
        """清單端點只回代碼 / 名稱 / 題數——教師選模板時不需要看到全部題幹，
        而把整包題目塞進清單會讓回應隨模板增加而膨脹。
        """
        rows = list_templates()
        assert len(rows) == len(SURVEY_TEMPLATES)
        for row in rows:
            assert not hasattr(row, "questions")
            assert row.question_count >= 1


class TestTemplateContent:
    def test_題型皆為合法值域(self) -> None:
        for template in SURVEY_TEMPLATES:
            for question in template.questions:
                assert question.question_type in ALL_SURVEY_QUESTION_TYPES, template.code

    def test_每題都符合自己題型的選項規則(self) -> None:
        """模板內容若違反規則，套用時會被自己的檢核擋下——那是最難查的一種
        「功能看起來壞掉但程式沒錯」。這裡拿**同一支規則**驗，兩邊不可能漂移。
        """
        for template in SURVEY_TEMPLATES:
            for question in template.questions:
                ensure_options_match_type(question.question_type, option_count=len(question.options))

    def test_單選題選項達下限(self) -> None:
        for template in SURVEY_TEMPLATES:
            for question in template.questions:
                if question.question_type == SURVEY_QUESTION_SINGLE:
                    assert len(question.options) >= MIN_OPTIONS, f"{template.code} / {question.stem}"

    def test_問答題無選項(self) -> None:
        for template in SURVEY_TEMPLATES:
            for question in template.questions:
                if question.question_type == SURVEY_QUESTION_TEXT:
                    assert question.options == ()

    def test_至少一組模板含問答題(self) -> None:
        """讓模板本身就是問答題型的示範——教師套用後立刻看得到兩種題型長什麼樣，
        不必自己摸索「問答題要怎麼建」。
        """
        has_text = any(q.question_type == SURVEY_QUESTION_TEXT for t in SURVEY_TEMPLATES for q in t.questions)
        assert has_text

    def test_題幹與選項皆非空白(self) -> None:
        for template in SURVEY_TEMPLATES:
            assert template.name.strip()
            for question in template.questions:
                assert question.stem.strip(), template.code
                for option in question.options:
                    assert option.strip(), template.code


class TestGetTemplate:
    def test_取得存在的模板(self) -> None:
        template = get_template(SURVEY_TEMPLATES[0].code)
        assert template.code == SURVEY_TEMPLATES[0].code

    def test_查無模板回_404(self) -> None:
        with pytest.raises(AppError) as exc:
            get_template("NO_SUCH_TEMPLATE")
        assert exc.value.status_code == 404
        assert exc.value.error_code == "ET_SURVEY_009"

    def test_模板為不可變(self) -> None:
        """模板是**共用的模組層常數**——若可變，某次套用改到它，之後每個教師拿到的
        都是被改過的內容，而且改動不落任何紀錄。以 frozen dataclass + tuple 防呆。
        """
        template = get_template(SURVEY_TEMPLATES[0].code)
        with pytest.raises((AttributeError, TypeError)):
            template.name = "偷改"  # type: ignore[misc]
        assert isinstance(template.questions, tuple)
        assert isinstance(template.questions[0].options, tuple)
