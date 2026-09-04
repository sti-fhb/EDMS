"""ET05 學習進度之純業務規則（US5 / #274）。

本檔是這張 issue 的重心——覆蓋率的三條規則、normalize、解鎖判定全部是純函式，
**完全不需要 DB 就能驗完**。

## 三條覆蓋率規則其實是同一個決定

| 規則 | spec |
|---|---|
| 倍速照算（2x 看完全片 = 100%）| FR-07 |
| 直接拉到結尾不算看過 | FR-06 |
| 重複觀看不加成 | FR-06 |

合起來就是：**只計算「播放頭實際走過的影片時間軸範圍」的聯集**。
"""

import pytest

from app.et.progress.rules import (
    COVERAGE_THRESHOLD_PCT,
    Segment,
    clamp_segment,
    coverage_pct,
    is_item_unlocked,
    merge_segments,
)

pytestmark = pytest.mark.unit


class TestMergeSegments:
    """區段聯集去重——`normalize` 與覆蓋率共用的核心。"""

    def test_無區段回空(self) -> None:
        assert merge_segments([]) == ()

    def test_不相交者原樣保留並排序(self) -> None:
        assert merge_segments([Segment(50, 60), Segment(10, 20)]) == (Segment(10, 20), Segment(50, 60))

    def test_重疊者合併(self) -> None:
        assert merge_segments([Segment(0, 60), Segment(30, 90)]) == (Segment(0, 90),)

    def test_相接者合併(self) -> None:
        """`[0,30]` 與 `[30,60]` 之間沒有未觀看的秒數，合併是無損的。"""
        assert merge_segments([Segment(0, 30), Segment(30, 60)]) == (Segment(0, 60),)

    def test_有間隔者不合併(self) -> None:
        """**間隔一秒也不能合併**——那一秒他沒看過。

        任何正數的「鄰近」門檻都會把未觀看的時間算進覆蓋率，與 FR-06 衝突。
        """
        assert merge_segments([Segment(0, 30), Segment(31, 60)]) == (Segment(0, 30), Segment(31, 60))

    def test_完全包含者被吸收(self) -> None:
        assert merge_segments([Segment(0, 100), Segment(20, 30)]) == (Segment(0, 100),)

    def test_多段連鎖合併(self) -> None:
        segments = [Segment(0, 10), Segment(5, 20), Segment(18, 25), Segment(40, 50)]
        assert merge_segments(segments) == (Segment(0, 25), Segment(40, 50))


class TestCoveragePct:
    """覆蓋率 = 區段**聯集** ÷ 影片總長。"""

    def test_無區段為零(self) -> None:
        assert coverage_pct([], duration_sec=100) == 0

    def test_看完全片為一百(self) -> None:
        assert coverage_pct([Segment(0, 100)], duration_sec=100) == 100

    def test_看一半為五十(self) -> None:
        assert coverage_pct([Segment(0, 50)], duration_sec=100) == 50

    def test_重複觀看不加成(self) -> None:
        """**本檔最重要的一條**（AC 14 / FR-06）。

        `data-model` §ET_PROGRESS_INTERVAL 曾寫「覆蓋率 = SUM(END−START)」——照那樣
        實作，學員把前半段看兩次就會得到 `50 + 50 = 100%`，而他從未看過後半段。
        本 issue 已修正該處措辭；這條測試釘住正確行為。
        """
        twice = [Segment(0, 50), Segment(0, 50)]
        assert coverage_pct(twice, duration_sec=100) == 50

    def test_部分重疊只算聯集(self) -> None:
        assert coverage_pct([Segment(0, 60), Segment(30, 90)], duration_sec=100) == 90

    def test_跳過的區段不計入(self) -> None:
        """FR-06：直接把進度條拉到結尾，跳過的範圍不產生區段。

        前端契約保證跳躍不上報；此處驗的是「就算只有前後兩段，中間也不會被補起來」。
        """
        assert coverage_pct([Segment(0, 10), Segment(90, 100)], duration_sec=100) == 20

    def test_倍速依影片時間軸而非牆鐘(self) -> None:
        """FR-07：2 倍速實際看完全片 = 100%。

        區段記的是 `currentTime`（影片時間軸），所以 2 倍速播 50 秒牆鐘會產生
        `[0,100]` 而非 `[0,50]`——倍速自然照算，後端不需要知道倍速是多少。
        """
        assert coverage_pct([Segment(0, 100)], duration_sec=100) == 100

    def test_上限為一百(self) -> None:
        """`COVERAGE_PCT` 為 `DECIMAL(5,2)`；異常上報不得讓它超過 100。"""
        assert coverage_pct([Segment(0, 200)], duration_sec=100) == 100

    def test_影片長度為零時回零而非除零(self) -> None:
        """`DURATION_SEC` 理論上必為正（上傳時由 ffprobe 取得），但資料異常不該 500。"""
        assert coverage_pct([Segment(0, 10)], duration_sec=0) == 0

    def test_normalize_不改變覆蓋率(self) -> None:
        """**normalize 是儲存壓縮，不是正確性前提**。

        這條保證了 AC 7（異常離開未 normalize，下次計算仍正確）——因為計算本身就會
        先聯集，有沒有先合併過都一樣。
        """
        raw = [Segment(0, 60), Segment(30, 90), Segment(85, 100)]
        merged = list(merge_segments(raw))
        assert coverage_pct(raw, duration_sec=100) == coverage_pct(merged, duration_sec=100)


class TestClampSegment:
    def test_超過影片長度者被裁切(self) -> None:
        assert clamp_segment(Segment(90, 150), duration_sec=100) == Segment(90, 100)

    def test_負數起點被裁切為零(self) -> None:
        assert clamp_segment(Segment(-5, 10), duration_sec=100) == Segment(0, 10)

    def test_完全落在範圍外者回_None(self) -> None:
        assert clamp_segment(Segment(150, 200), duration_sec=100) is None

    def test_裁切後長度為零者回_None(self) -> None:
        """起訖相同的區段沒有意義，不該寫入 DB（`END_SEC > START_SEC` 為業務規則）。"""
        assert clamp_segment(Segment(50, 50), duration_sec=100) is None


class TestIsItemUnlocked:
    """章節內依序解鎖（#274 SA Q2 裁示 A）。"""

    def test_第一項恆解鎖(self) -> None:
        assert is_item_unlocked(previous_completed=None, self_completed=False)

    def test_前一項完成則解鎖(self) -> None:
        assert is_item_unlocked(previous_completed=True, self_completed=False)

    def test_前一項未完成則鎖定(self) -> None:
        """裁示 A 擋的就是這個——尤其是「還沒看教材就先點測驗」。

        `ET_QUIZ.MAX_RETRY` 有重考次數上限；讓學員能先點進測驗，會把那個限制變成陷阱。
        """
        assert not is_item_unlocked(previous_completed=False, self_completed=False)

    def test_已完成者不再上鎖(self) -> None:
        """回頭複習照常——依序解鎖擋的只有「還沒學過的」。

        少了這條，學員完成第 3 項後想回看第 1 項會被自己的進度擋住，那顯然不對。
        """
        assert is_item_unlocked(previous_completed=False, self_completed=True)


class TestThreshold:
    def test_門檻為八十(self) -> None:
        assert COVERAGE_THRESHOLD_PCT == 80
