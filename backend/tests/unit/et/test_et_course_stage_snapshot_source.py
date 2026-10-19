"""「更新」的檢核讀的是**暫存值**，不是活表值（#720）。

## 🔴 這是本 issue 風險最高的一處

`to_course_snapshot` 餵給 `evaluate_publish` 的四個參數原本**全部取自活表**，而其中三個
（起訖時間、受訓對象組數）在 #720 之後有了暫存版本。

不換邊的症狀是**檢核通過但生效後不合格**：教師把訖止時間改成已過的時點、按「更新」，
檢核讀活表的舊值（合格）而放行，套用之後活表變成不合格——而發布檢核的全部意義就是
不讓那件事發生。

## ⚠️ `status` 仍取活表

狀態轉換（發布 / 關閉 / 再開課）不走暫存，課程狀態不是教師在基本資料區編輯的東西。
四個參數裡**只換三個**——這正是容易寫錯的地方，所以每一個都有獨立斷言。
"""

from datetime import datetime, timezone

import pytest

from app.et.constants import COURSE_PUBLISHED
from app.et.course.stage_rules import (
    ENTITY_CHAPTER,
    ENTITY_COURSE,
    ENTITY_COURSE_TAG,
    StageNode,
    to_course_snapshot,
)

pytestmark = pytest.mark.unit

_LIVE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_LIVE_END = datetime(2020, 12, 31, tzinfo=timezone.utc)
_STAGED_START = datetime(2030, 1, 1, tzinfo=timezone.utc)
_STAGED_END = datetime(2030, 12, 31, tzinfo=timezone.utc)


def _course_node(**payload) -> StageNode:
    base = {
        "course_name": "課程",
        "description": None,
        "open_start_at": _STAGED_START,
        "open_end_at": _STAGED_END,
        "require_approval": False,
    }
    return StageNode(
        stage_id=1, entity_type=ENTITY_COURSE, source_id=10, parent_stage_id=None, sort_order=1, payload=base | payload
    )


def _tag_nodes(n: int) -> list[StageNode]:
    return [
        StageNode(
            stage_id=100 + i,
            entity_type=ENTITY_COURSE_TAG,
            source_id=200 + i,
            parent_stage_id=1,
            sort_order=i + 1,
            payload={"tag_id": 2, "unit_tag_id": 101 + i},
        )
        for i in range(n)
    ]


def _snapshot(nodes: list[StageNode]):
    return to_course_snapshot(nodes, status=COURSE_PUBLISHED)


class TestScheduleFromStage:
    def test_起訖時間取暫存值(self) -> None:
        snap = _snapshot([_course_node(), *_tag_nodes(1)])

        assert snap.open_start_at == _STAGED_START
        assert snap.open_end_at == _STAGED_END

    def test_暫存清掉訖止時間時快照就是空的(self) -> None:
        """🥇 **本組的核心**：教師清掉訖止、按「更新」，檢核必須看到「空的」而被擋。

        讀活表的話會看到舊的合法值而放行——而套用之後活表就是空的了。
        """
        snap = _snapshot([_course_node(open_end_at=None), *_tag_nodes(1)])

        assert snap.open_end_at is None

    def test_反向錨點_活表的值不會洩進快照(self) -> None:
        """少了它，把實作寫成「兩個都看、暫存為空就退回活表」也會讓上面兩條通過
        ——而那正好是本 issue 要消滅的行為。"""
        snap = _snapshot([_course_node(open_start_at=None, open_end_at=None), *_tag_nodes(1)])

        assert snap.open_start_at is None, f"活表的 {_LIVE_START} 不該出現在快照裡"
        assert snap.open_end_at is None, f"活表的 {_LIVE_END} 不該出現在快照裡"


class TestTagCountFromStage:
    def test_受訓對象組數數的是暫存節點(self) -> None:
        assert _snapshot([_course_node(), *_tag_nodes(3)]).tag_count == 3

    def test_暫存沒有受訓對象時為零(self) -> None:
        """教師把配對全刪光（已關閉課程可以），按「更新」要被 `BLOCK_NO_TAG` 擋下。"""
        assert _snapshot([_course_node()]).tag_count == 0


class TestStatusStaysLive:
    def test_狀態仍由呼叫端給定而非暫存(self) -> None:
        """⚠️ 四個參數裡**只換三個**。

        狀態若也取暫存，教師按「更新」就會把課程狀態改回編輯開始那一刻的值，
        等於繞過整條狀態機——而那在 `COURSE_SYSTEM_FIELDS` 已經擋在搬運那一層，
        這裡是第二道。
        """
        assert _snapshot([_course_node(), *_tag_nodes(1)]).status == COURSE_PUBLISHED


class TestMissingCourseNode:
    def test_沒有課程節點時明確報錯而非靜默給_None(self) -> None:
        """🔴 暫存樹少了課程節點 ＝ 它是舊版本留下的（本 issue 之前 seed 的）。

        靜默回 `None` 會讓檢核報「起訖時間未填」——教師看著畫面上明明填著的時間，
        而真正的原因是暫存樹的結構不對。那種錯誤訊息比沒有訊息更糟。
        """
        with pytest.raises(ValueError, match="課程節點"):
            _snapshot(
                [
                    StageNode(
                        stage_id=5,
                        entity_type=ENTITY_CHAPTER,
                        source_id=50,
                        parent_stage_id=None,
                        sort_order=1,
                        payload={"chapter_name": "第一章"},
                    )
                ]
            )
