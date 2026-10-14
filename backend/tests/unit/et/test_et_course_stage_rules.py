"""暫存內容樹 → `CourseSnapshot` 的純規則（#631）。

本層存在的理由只有一個：**讓 `evaluate_publish` 一行都不用改**。「更新」要檢核的是
「即將生效的內容」，而那份內容在暫存區；只要能把暫存樹組成同一個 `CourseSnapshot`，
十項 `BLOCK_*` 全部原封不動重用。

⚠️ 這裡的斷言必須與 `publish_repository` 由活表組快照的行為**逐條對齊**——兩邊若分歧，
「更新」與「發布」會對同一份內容給出不同的檢核結果，而那種不一致不會有任何錯誤訊息。
"""

from datetime import datetime, timezone

import pytest

from app.et.constants import COURSE_PUBLISHED, ITEM_MATERIAL, ITEM_QUIZ
from app.et.course.publish_rules import (
    BLOCK_CHAPTER_EMPTY,
    BLOCK_ITEM_NO_TITLE,
    BLOCK_QUIZ_NO_QUESTION,
    BLOCK_QUIZ_POINTS,
    BLOCK_SURVEY_NO_QUESTION,
    evaluate_publish,
)
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_ITEM,
    ENTITY_MATERIAL,
    ENTITY_MATERIAL_DOC,
    ENTITY_OPTION,
    ENTITY_QUESTION,
    ENTITY_QUIZ,
    ENTITY_SURVEY,
    ENTITY_SURVEY_QUESTION,
    StageNode,
    to_course_snapshot,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
_END = datetime(2027, 10, 14, tzinfo=timezone.utc)


def _node(
    stage_id: int,
    entity_type: str,
    *,
    parent: int | None = None,
    source_id: int | None = None,
    sort_order: int = 1,
    **payload,
) -> StageNode:
    return StageNode(
        stage_id=stage_id,
        entity_type=entity_type,
        source_id=source_id,
        parent_stage_id=parent,
        sort_order=sort_order,
        payload=payload,
    )


def _snapshot(nodes, *, tag_count: int = 1):
    """⚠️ 起訖時間與受訓對象都給齊——本檔要驗的是**內容**那幾項 `BLOCK_*`。

    少給任何一個都會多出 `BLOCK_NO_SCHEDULE` / `BLOCK_NO_TAG`，讓「完整的樹不產生
    任何缺漏」那條永遠紅，而紅的理由與本層無關。
    """
    return to_course_snapshot(
        nodes,
        status=COURSE_PUBLISHED,
        open_start_at=_NOW,
        open_end_at=_END,
        tag_count=tag_count,
    )


def _chapter_with_material(ch_id: int, item_id: int, mat_id: int, *, name: str = "教材甲"):
    """一條最小的「章節 → 項目 → 教材」鏈。"""
    return [
        _node(ch_id, ENTITY_CHAPTER, chapter_name="第一章"),
        _node(item_id, ENTITY_ITEM, parent=ch_id, item_type=ITEM_MATERIAL),
        _node(mat_id, ENTITY_MATERIAL, parent=item_id, material_name=name),
    ]


class TestChapters:
    def test_空樹沒有章節(self) -> None:
        snap = _snapshot([])

        assert snap.chapter_count == 0
        assert snap.chapters == ()

    def test_沒有項目的章節仍須列出(self) -> None:
        """🔴 沒有項目的章節**正是** `BLOCK_CHAPTER_EMPTY` 要抓的對象。

        活表那側是以 `LEFT OUTER JOIN` 達成（`publish_repository._chapter_summaries`
        的註解寫明 INNER 會讓它們整個消失）。本層以「子節點計數」達成同一件事——
        計數為 0 的章節照樣產生一筆摘要。
        """
        snap = _snapshot([_node(1, ENTITY_CHAPTER, chapter_name="空章")])

        assert len(snap.chapters) == 1
        assert snap.chapters[0].item_count == 0

    def test_章節的項目數由子節點導出(self) -> None:
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="第一章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL),
            _node(12, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ),
            _node(2, ENTITY_CHAPTER, chapter_name="第二章", sort_order=2),
            _node(21, ENTITY_ITEM, parent=2, item_type=ITEM_MATERIAL),
        ]

        snap = _snapshot(nodes)

        assert [c.item_count for c in snap.chapters] == [2, 1]

    def test_章節依_sort_order_排序(self) -> None:
        """缺漏清單的順序要與教師畫面上的章節順序一致（比照活表那側）。"""
        nodes = [
            _node(9, ENTITY_CHAPTER, chapter_name="後面的", sort_order=5),
            _node(3, ENTITY_CHAPTER, chapter_name="前面的", sort_order=1),
        ]

        snap = _snapshot(nodes)

        assert [c.chapter_id for c in snap.chapters] == [3, 9]


class TestItems:
    def test_項目名稱取自教材子節點(self) -> None:
        """⚠️ 名稱不在項目本身——活表那側以 `coalesce(教材名, 測驗名, "")` 取得。"""
        snap = _snapshot(_chapter_with_material(1, 11, 111, name="採血操作"))

        assert [(i.item_id, i.title) for i in snap.items] == [(11, "採血操作")]

    def test_項目名稱取自測驗子節點(self) -> None:
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="第一章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ),
            _node(111, ENTITY_QUIZ, parent=11, quiz_name="期末測驗"),
        ]

        snap = _snapshot(nodes)

        assert [(i.item_id, i.title) for i in snap.items] == [(11, "期末測驗")]

    def test_項目沒有教材也沒有測驗時名稱為空字串(self) -> None:
        """🔴 不可回 `None`——`evaluate_publish` 會對 `title` 呼叫 `.strip()`。

        活表那側 `coalesce` 的第三個參數 `""` 正是為此（其 docstring 寫明「不是防禦性冗餘」）。
        """
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="第一章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL),
        ]

        snap = _snapshot(nodes)

        assert snap.items[0].title == ""

    def test_項目依章節順序再依項目順序排序(self) -> None:
        nodes = [
            _node(2, ENTITY_CHAPTER, chapter_name="第二章", sort_order=2),
            _node(22, ENTITY_ITEM, parent=2, item_type=ITEM_MATERIAL, sort_order=2),
            _node(21, ENTITY_ITEM, parent=2, item_type=ITEM_MATERIAL, sort_order=1),
            _node(1, ENTITY_CHAPTER, chapter_name="第一章", sort_order=1),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL, sort_order=1),
        ]

        snap = _snapshot(nodes)

        assert [i.item_id for i in snap.items] == [11, 21, 22]

    def test_教材數為教材節點數(self) -> None:
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(12, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL, sort_order=2),
            _node(112, ENTITY_MATERIAL, parent=12, material_name="教材乙"),
        ]

        snap = _snapshot(nodes)

        assert snap.material_count == 2


class TestQuizzes:
    def test_題數與配分總和由題目子節點導出(self) -> None:
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="第一章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ),
            _node(111, ENTITY_QUIZ, parent=11, quiz_name="測驗"),
            _node(1111, ENTITY_QUESTION, parent=111, points=60, stem="Q1"),
            _node(1112, ENTITY_QUESTION, parent=111, points=40, stem="Q2", sort_order=2),
            _node(11111, ENTITY_OPTION, parent=1111, option_text="A"),
        ]

        snap = _snapshot(nodes)

        assert [(q.quiz_id, q.question_count, q.points_total) for q in snap.quizzes] == [(111, 2, 100)]

    def test_零題測驗仍須列出(self) -> None:
        """同 `test_沒有項目的章節仍須列出`：零題測驗正是 `BLOCK_QUIZ_NO_QUESTION` 的對象。

        活表那側 `_quiz_summaries` 的 docstring 記著它踩過同一個 INNER JOIN 的坑。
        """
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="第一章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ),
            _node(111, ENTITY_QUIZ, parent=11, quiz_name="空測驗"),
        ]

        snap = _snapshot(nodes)

        assert [(q.quiz_id, q.question_count, q.points_total) for q in snap.quizzes] == [(111, 0, 0)]


class TestSurvey:
    def test_沒有問卷時題數為_None(self) -> None:
        """`None` ＝ 沒有問卷（選配，不擋）；`0` ＝ 有問卷但零題（要擋）。"""
        snap = _snapshot(_chapter_with_material(1, 11, 111))

        assert snap.survey_question_count is None

    def test_有問卷但零題時為_0(self) -> None:
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(5, ENTITY_SURVEY, survey_name="課後問卷", is_active=True)
        ]

        snap = _snapshot(nodes)

        assert snap.survey_question_count == 0

    def test_已停用的問卷視同沒有問卷(self) -> None:
        """#611：停用後學員端不顯示入口，有沒有題目都影響不到學員。

        ⚠️ 活表那側是以查詢條件 `EtSurvey.is_active.is_(True)` 達成，**規則名在該檔零命中**；
        本層改以 payload 的旗標判定。兩邊要同時改，否則「更新」會擋下「發布」放行的課程。
        """
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(5, ENTITY_SURVEY, survey_name="停用的問卷", is_active=False)
        ]

        snap = _snapshot(nodes)

        assert snap.survey_question_count is None

    def test_啟用中的問卷計入題數(self) -> None:
        """正向錨點：少了這條，把問卷整個忽略掉也會讓上面兩條通過。"""
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(5, ENTITY_SURVEY, survey_name="課後問卷", is_active=True),
            _node(51, ENTITY_SURVEY_QUESTION, parent=5, stem="滿意度"),
            _node(52, ENTITY_SURVEY_QUESTION, parent=5, stem="建議", sort_order=2),
        ]

        snap = _snapshot(nodes)

        assert snap.survey_question_count == 2


class TestDocIds:
    def test_彙整所有文件引用(self) -> None:
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(1111, ENTITY_MATERIAL_DOC, parent=111, doc_id="DM-TRAINING-000001"),
            _node(1112, ENTITY_MATERIAL_DOC, parent=111, doc_id="DM-TRAINING-000002", sort_order=2),
        ]

        snap = _snapshot(nodes)

        assert snap.doc_ids == frozenset({"DM-TRAINING-000001", "DM-TRAINING-000002"})


class TestIdentifiersAreStageIds:
    def test_識別碼一律用_stage_id_而非_source_id(self) -> None:
        """🔴 **設計決定**：缺漏的 `target_id` 用暫存列的 id，不用活表的 id。

        `PublishBlocker.target_id` 是給前端定位到畫面區塊用的。PR 2 之後編輯頁讀的是
        暫存樹，畫面上每個區塊帶的就是 `stage_id`；若這裡回 `source_id`，新增的內容
        （還沒有活表 id）就無從定位，而既有內容又會回一個畫面上不存在的號碼。

        ⚠️ 兩者的號碼空間**會重疊**（都是 BIGINT identity），所以回錯了不會爆、只會
        標錯區塊——這條測試是唯一會發現的地方。
        """
        nodes = [
            _node(900, ENTITY_CHAPTER, source_id=7, chapter_name="既有章節"),
            _node(901, ENTITY_ITEM, parent=900, source_id=8, item_type=ITEM_QUIZ),
            _node(902, ENTITY_QUIZ, parent=901, source_id=9, quiz_name="既有測驗"),
        ]

        snap = _snapshot(nodes)

        assert snap.chapters[0].chapter_id == 900, "章節用 stage_id"
        assert snap.items[0].item_id == 901, "項目用 stage_id"
        assert snap.quizzes[0].quiz_id == 902, "測驗用 stage_id"


class TestFeedsExistingEvaluatePublish:
    """🥇 本層的目的：組出的快照餵給**既有的** `evaluate_publish`，檢核規則一行不改。"""

    def test_完整的暫存樹不產生任何缺漏(self) -> None:
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(12, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ, sort_order=2),
            _node(112, ENTITY_QUIZ, parent=12, quiz_name="測驗"),
            _node(1121, ENTITY_QUESTION, parent=112, points=100, stem="Q1"),
        ]

        blockers = evaluate_publish(_snapshot(nodes), obsolete_doc_ids=frozenset())

        assert blockers == ()

    def test_空章節零題測驗未命名項目配分不足都被既有規則抓到(self) -> None:
        """一次驗四條 `BLOCK_*` 都能由暫存樹觸發。"""
        nodes = [
            _node(1, ENTITY_CHAPTER, chapter_name="有東西的章"),
            _node(11, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL),
            _node(111, ENTITY_MATERIAL, parent=11, material_name="教材"),
            # 未命名的項目（其教材沒有名稱）
            _node(12, ENTITY_ITEM, parent=1, item_type=ITEM_MATERIAL, sort_order=2),
            _node(112, ENTITY_MATERIAL, parent=12, material_name="  "),
            # 零題測驗 + 配分不足
            _node(13, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ, sort_order=3),
            _node(113, ENTITY_QUIZ, parent=13, quiz_name="空測驗"),
            _node(14, ENTITY_ITEM, parent=1, item_type=ITEM_QUIZ, sort_order=4),
            _node(114, ENTITY_QUIZ, parent=14, quiz_name="配分不足"),
            _node(1141, ENTITY_QUESTION, parent=114, points=30, stem="Q1"),
            # 空章節
            _node(2, ENTITY_CHAPTER, chapter_name="空章", sort_order=2),
            # 零題的啟用問卷
            _node(5, ENTITY_SURVEY, survey_name="問卷", is_active=True),
        ]

        codes = {b.code for b in evaluate_publish(_snapshot(nodes), obsolete_doc_ids=frozenset())}

        assert BLOCK_CHAPTER_EMPTY in codes
        assert BLOCK_ITEM_NO_TITLE in codes
        assert BLOCK_QUIZ_NO_QUESTION in codes
        assert BLOCK_QUIZ_POINTS in codes
        assert BLOCK_SURVEY_NO_QUESTION in codes

    def test_缺漏指向的是_stage_id(self) -> None:
        """承 `TestIdentifiersAreStageIds`：一路傳到 `PublishBlocker.target_id` 都要是暫存 id。"""
        nodes = _chapter_with_material(1, 11, 111) + [
            _node(2, ENTITY_CHAPTER, source_id=77, chapter_name="空章", sort_order=2),
        ]

        blockers = evaluate_publish(_snapshot(nodes), obsolete_doc_ids=frozenset())
        empty = [b for b in blockers if b.code == BLOCK_CHAPTER_EMPTY]

        assert [b.target_id for b in empty] == [2]
