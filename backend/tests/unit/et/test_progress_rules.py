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
    ItemState,
    Segment,
    build_item_state,
    clamp_segment,
    coverage_pct,
    first_blocking_item,
    is_item_unlocked,
    locked_item_ids,
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


class TestBuildItemState:
    """`treat_as_done` 的餵值——AC 12「測驗未及格阻擋解鎖」的判斷點（#361 AC 7）。

    🔴 **本類是 `build_item_state` 的第一批直接測試**。在此之前它沒有任何 unit test，
    那一行只被整合測試間接碰到——而它一旦與側欄分岔，表現是「側欄顯示解鎖但後端擋下」，
    正是整合測試最不容易自然抓到的一種。
    """

    def test_未通過的測驗擋住後續(self) -> None:
        """AC 12 的本體：沒通過就是沒完成，後面的東西不該開。

        2026-09-22 之前這裡恆為 `True`（`or item_type == ITEM_QUIZ`），理由是當時
        `ET_QUIZ_RETRY_RESET` 全專案無人寫入、次數用盡即永久鎖死。ET-9（#329）交付
        重置後該前提消失。
        """
        state = build_item_state(7, completed_ids=set(), zero_question_quiz_item_ids=frozenset())

        assert state.completed is False
        assert state.treat_as_done is False, "未通過的測驗必須擋住後續，否則 AC 12 等於沒啟用"

    def test_通過後不再擋(self) -> None:
        state = build_item_state(7, completed_ids={7}, zero_question_quiz_item_ids=frozenset())

        assert (state.completed, state.treat_as_done) == (True, True)

    def test_零題測驗不當閘門(self) -> None:
        """🔴 **0 題的測驗沒有任何逃生門**，故不得拿它當閘門。

        `attempt/service` 對 0 題測驗直接回 404（建一個零題 attempt 會白吃一次次數），
        學員因此**連考都考不了**、永遠拿不到 `IS_COMPLETED`。而 ET03 的重置鈕也不會
        出現——`can_reset_retry` 要求 `used > max_retry`，他連一次都用不掉。

        形狀與 `locked_item_ids` 對「空章節」的處理完全相同：不擋路，改由發布檢核
        （`BLOCK_QUIZ_NO_QUESTION`）在上游擋住。⛔ 不要改成「擋住並提示」——教師把
        題目全刪掉重建的那段時間，全班會卡在一份開不起來的考卷前。
        """
        state = build_item_state(7, completed_ids=set(), zero_question_quiz_item_ids=frozenset({7}))

        assert state.completed is False, "側欄仍不打勾——他確實沒通過"
        assert state.treat_as_done is True, "但不得擋住後續"


def _item(item_id: int, *, completed: bool = False, treat_as_done: bool | None = None) -> ItemState:
    """測試用項目。`treat_as_done` 未指定時等同 `completed`（一般教材項目的情形）。"""
    return ItemState(
        item_id=item_id,
        completed=completed,
        treat_as_done=completed if treat_as_done is None else treat_as_done,
    )


class TestLockedItemIds:
    """章節依序 + 章節內依序的整體解鎖判定（AC 5 / AC 6 + 裁示 Q2=A）。"""

    def test_全新學員只解鎖第一章第一項(self) -> None:
        chapters = [[_item(1), _item(2)], [_item(3), _item(4)]]
        assert locked_item_ids(chapters) == frozenset({2, 3, 4})

    def test_章節內依序解鎖(self) -> None:
        chapters = [[_item(1, completed=True), _item(2), _item(3)]]
        assert locked_item_ids(chapters) == frozenset({3})

    def test_前一章未全部完成則下一章全鎖(self) -> None:
        """AC 6：覆蓋率未達時阻擋切換至下一章節。"""
        chapters = [[_item(1, completed=True), _item(2)], [_item(3), _item(4)]]
        assert locked_item_ids(chapters) == frozenset({3, 4})

    def test_前一章全部完成則下一章第一項解鎖(self) -> None:
        chapters = [[_item(1, completed=True), _item(2, completed=True)], [_item(3), _item(4)]]
        assert locked_item_ids(chapters) == frozenset({4})

    def test_已完成項目永不鎖定(self) -> None:
        """教師事後調整章節順序時，學員已學過的東西不該突然被鎖回去。

        這裡第 2 章的項目 4 已完成，但第 1 章尚未全部完成——章節層說該鎖，
        「已完成永不鎖」優先。
        """
        chapters = [[_item(1), _item(2)], [_item(3), _item(4, completed=True)]]
        assert 4 not in locked_item_ids(chapters)

    def test_空章節不擋路(self) -> None:
        """**沒有項目的章節視為已完成**。

        反過來會讓教師建了空章節之後，整門課程的後半段永久鎖死，而畫面上完全看不出
        原因——側欄只會顯示一整排 🔒，沒有任何可操作的下一步。
        """
        chapters: list[list[ItemState]] = [[], [_item(1), _item(2)]]
        assert locked_item_ids(chapters) == frozenset({2})

    def test_視為完成但未完成的項目不擋住後續(self) -> None:
        """`treat_as_done=True` 而 `completed=False` 的項目不擋路，但自己不打勾。

        ⚠️ **本條驗的是 `locked_item_ids` 怎麼用這兩個欄位，不是誰會產生這種組合。**
        2026-09-22 之前唯一的來源是「測驗恆視為通過」（AC 12 未啟用）；AC 12 啟用後
        改為只有 **0 題的測驗**會落在這個組合（見 `TestBuildItemState`）。兩者的共同
        點是「這一項現在不可能完成，擋住它等於永久鎖死」。

        ⛔ 不要因為舊名稱叫「測驗項目不擋住後續」就把它讀成「測驗永遠不擋」——那已經
        不成立了。
        """
        ungated = _item(2, completed=False, treat_as_done=True)
        chapters = [[_item(1, completed=True), ungated, _item(3)], [_item(4)]]
        # 它自己未完成（側欄不打勾）但**不擋住**其後的項目 3
        assert locked_item_ids(chapters) == frozenset({4})

    def test_視為完成但未完成的項目在章末也不擋住下一章(self) -> None:
        """接上：它在章末時，也不能擋住整個下一章。"""
        ungated = _item(2, completed=False, treat_as_done=True)
        chapters = [[_item(1, completed=True), ungated], [_item(3), _item(4)]]
        assert locked_item_ids(chapters) == frozenset({4})

    def test_無章節回空集合(self) -> None:
        assert locked_item_ids([]) == frozenset()


class TestFirstBlockingItem:
    """學習前緣——供 ET05 對鎖定項目給出**正確**的提示（`spec_us5` AC 12）。

    AC 12 啟用後，鎖定多了「測驗未通過」這個成因；前端寫死的「請先完成本章節之影片
    學習」會把考不過的學員指向錯的動作。
    """

    def test_回第一個未完成者(self) -> None:
        chapters = [[_item(1, completed=True), _item(2)], [_item(3)]]
        assert first_blocking_item(chapters) == 2

    def test_跨章節仍取最早者(self) -> None:
        """⛔ 不是「擋住該項的緊鄰前一項」。

        第 1 章的項目 2 沒完成 → 第 2 章整章鎖著。對第 2 章的項目該說的是「先去做
        項目 2」，而不是指向同樣鎖著的第 1 章末項。
        """
        chapters = [[_item(1, completed=True), _item(2), _item(3)], [_item(4)]]
        assert first_blocking_item(chapters) == 2

    def test_全部完成回_None(self) -> None:
        chapters = [[_item(1, completed=True)], [_item(2, completed=True)]]
        assert first_blocking_item(chapters) is None

    def test_零題測驗不算前緣(self) -> None:
        """它不擋路，自然也不是「學員該去做的下一件事」——指向它只會讓他更迷惑。"""
        zero_question_quiz = _item(1, completed=False, treat_as_done=True)
        chapters = [[zero_question_quiz, _item(2)]]
        assert first_blocking_item(chapters) == 2

    def test_空章節跳過(self) -> None:
        chapters: list[list[ItemState]] = [[], [_item(1)]]
        assert first_blocking_item(chapters) == 1

    def test_無章節回_None(self) -> None:
        assert first_blocking_item([]) is None


class TestThreshold:
    def test_門檻為八十(self) -> None:
        assert COVERAGE_THRESHOLD_PCT == 80
