"""`stage_apply` 裡**不碰 DB** 的那幾個判斷（#631）。

套用階段的主體要真 DB，但它夾著幾段純計算；而那幾段崩潰的後果是整支「更新」回 500
——教師看到的不是「哪裡不能改」，而是一個他既修不了也看不懂的錯誤。
"""

from app.et.course.stage_apply import _structure_sort_key, _survey_structure
from app.et.course.stage_rules import ENTITY_SURVEY_OPTION, ENTITY_SURVEY_QUESTION


def _child_of(nodes, parent_key, entity_type):
    """測試用的取子函式，形狀比照 `_ensure_survey_not_frozen` 裡的兩個閉包。"""
    return [n for (key, et), n in nodes if key == parent_key and et == entity_type]


class TestStructureSortKey:
    """🔴 排序鍵不可以是 `(sort_order, source_id)`（2026-10-18 security review L-7）。

    第 0 格是 `SOURCE_ID`，而**本次編輯新增的節點那一格是 `None`**。
    """

    def test_同一個_sort_order_下新舊節點混排不會爆(self) -> None:
        """⚠️ 這就是 bug 本身——`sorted` 只有在第一格打平時才會去比第二格。

        舊寫法在這組輸入上丟 `TypeError: '<' not supported between 'NoneType' and 'int'`，
        而它發生在凍結守門裡 ⇒ 整支「更新」回 500。
        """
        nodes = [(7, 1, "既有題"), (None, 1, "新加的題")]

        ordered = sorted(nodes, key=_structure_sort_key)

        assert ordered == [(None, 1, "新加的題"), (7, 1, "既有題")], "沒有活表 id 的排前面（穩定、可重現即可）"

    def test_sort_order_仍是第一順位(self) -> None:
        """正向錨點：少了它，把鍵寫成「只看 source_id」也會讓上一條通過。"""
        nodes = [(3, 2, "第二題"), (None, 1, "第一題")]

        assert [n[2] for n in sorted(nodes, key=_structure_sort_key)] == ["第一題", "第二題"]


class TestSurveyStructure:
    def test_新增題目與既有題目同序號時仍組得出結構(self) -> None:
        """端到端地驗上面那把鍵真的被 `_survey_structure` 用上。

        ⭐ 只測 `_structure_sort_key` 不夠——它可以是對的，而 `_survey_structure` 裡
        還留著一行舊的 `key=lambda n: (n[1], n[0])`（實際上原本有**兩行**）。
        """
        nodes = [
            (("S", ENTITY_SURVEY_QUESTION), (10, 1, "既有題", "SINGLE", "Q10")),
            (("S", ENTITY_SURVEY_QUESTION), (None, 1, "新加的題", "SINGLE", "Q_new")),
            (("Q10", ENTITY_SURVEY_OPTION), (99, 1, "好")),
            (("Q_new", ENTITY_SURVEY_OPTION), (None, 1, "好")),
            (("Q_new", ENTITY_SURVEY_OPTION), (98, 1, "普通")),
        ]

        structure = _survey_structure(nodes, survey_key="S", child_of=_child_of)

        assert [q[2] for q in structure] == ["新加的題", "既有題"]
        assert structure[0][4] == ((None, 1, "好"), (98, 1, "普通")), "選項那層也要用同一把鍵"
