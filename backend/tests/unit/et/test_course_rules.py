"""ET 課程 / 章節之純業務規則 unit test（#202）。

依 sti-testing「拿掉真 DB 仍驗得了就寫 unit」原則——本檔所驗規則皆為集合與字串運算，
不需 DB。需查 `ET_TAG.IS_ACTIVE`、`ET_PROGRESS` 連帶刪除等真互動者寫 integration。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.rules import (
    ensure_closable,
    ensure_deletable,
    ensure_item_reorder_complete,
    ensure_owner,
    ensure_reopen_schedule,
    ensure_reopenable,
    ensure_reorder_complete,
    ensure_tag_change_allowed,
    is_effectively_closed,
    resequence,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)


class TestEnsureOwner:
    """擁有權判定（spec.md §擁有權判定）：他人課程僅可閱覽。"""

    def test_擁有者可通過(self) -> None:
        ensure_owner(owner_id="u1", actor_id="u1")

    def test_非擁有者被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_owner(owner_id="u1", actor_id="u2")
        assert exc.value.status_code == 403
        assert exc.value.error_code == "ET_COURSE_002"

    def test_錯誤訊息不含使用者_id(self) -> None:
        """per sti-error-codes：error_message 不得嵌入動態值。"""
        with pytest.raises(AppError) as exc:
            ensure_owner(owner_id="u1", actor_id="u2")
        assert "u1" not in exc.value.detail and "u2" not in exc.value.detail


class TestEnsureTagChangeAllowed:
    """FR-ET-US3-02：草稿自由增刪；已發布僅可新增、不可移除。"""

    def test_草稿可自由增刪(self) -> None:
        ensure_tag_change_allowed(COURSE_DRAFT, current={1, 2}, desired={2, 3})

    def test_草稿可清空(self) -> None:
        ensure_tag_change_allowed(COURSE_DRAFT, current={1, 2}, desired=set())

    def test_已發布可新增(self) -> None:
        ensure_tag_change_allowed(COURSE_PUBLISHED, current={1}, desired={1, 2})

    def test_已發布移除被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_tag_change_allowed(COURSE_PUBLISHED, current={1, 2}, desired={1})
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_COURSE_003"

    def test_已關閉亦不可移除(self) -> None:
        """狀態機為 PUBLISHED ⇄ CLOSED，關閉只是暫時；標籤保護不因關閉而放寬。"""
        with pytest.raises(AppError):
            ensure_tag_change_allowed(COURSE_CLOSED, current={1, 2}, desired={1})

    def test_已發布未變動不觸發(self) -> None:
        ensure_tag_change_allowed(COURSE_PUBLISHED, current={1, 2}, desired={1, 2})


class TestEnsureDeletable:
    """SA 裁示 Q1：僅草稿課程可刪除；已發布 / 已關閉改用 US11 之「關閉」。"""

    def test_草稿可刪(self) -> None:
        ensure_deletable(COURSE_DRAFT)

    @pytest.mark.parametrize("status", [COURSE_PUBLISHED, COURSE_CLOSED])
    def test_非草稿被擋(self, status: str) -> None:
        with pytest.raises(AppError) as exc:
            ensure_deletable(status)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_COURSE_005"


class TestResequence:
    """章節重排：以完整順序陣列重算 SORT_ORDER（自 1 起）。"""

    def test_依陣列順序自_1_起編號(self) -> None:
        assert resequence([30, 10, 20]) == {30: 1, 10: 2, 20: 3}

    def test_單一章節(self) -> None:
        assert resequence([7]) == {7: 1}

    def test_空清單(self) -> None:
        assert resequence([]) == {}


class TestEnsureReorderComplete:
    """重排採「完整陣列」而非相對移動——避免並行下的順序漂移。"""

    def test_集合一致時通過(self) -> None:
        ensure_reorder_complete(current_ids={1, 2, 3}, requested=[3, 1, 2])

    def test_缺漏章節被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_reorder_complete(current_ids={1, 2, 3}, requested=[1, 2])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_CHAPTER_002"

    def test_多出不屬本課程之章節被擋(self) -> None:
        """防越權：把別人課程的章節 id 塞進來重排。"""
        with pytest.raises(AppError) as exc:
            ensure_reorder_complete(current_ids={1, 2}, requested=[1, 2, 99])
        assert exc.value.error_code == "ET_CHAPTER_002"

    def test_重複_id_被擋(self) -> None:
        """[1,1,2] 之集合與 {1,2} 相同，若只比對集合會漏掉；須另檢長度。"""
        with pytest.raises(AppError) as exc:
            ensure_reorder_complete(current_ids={1, 2}, requested=[1, 1, 2])
        assert exc.value.error_code == "ET_CHAPTER_002"


class TestEnsureItemReorderComplete:
    """項目重排判定（#203）：與章節同一邏輯、不同錯誤碼。"""

    def test_集合一致時通過(self) -> None:
        ensure_item_reorder_complete(current_ids={10, 11, 12}, requested=[12, 10, 11])

    def test_缺漏項目被擋(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_item_reorder_complete(current_ids={10, 11, 12}, requested=[10, 11])
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_ITEM_002"

    def test_多出不屬本章節之項目被擋(self) -> None:
        """防越權：把別的章節（甚至別人課程）的項目 id 塞進來重排。"""
        with pytest.raises(AppError) as exc:
            ensure_item_reorder_complete(current_ids={10, 11}, requested=[10, 11, 99])
        assert exc.value.error_code == "ET_ITEM_002"

    def test_重複_id_被擋(self) -> None:
        """[10,10,11] 之集合與 {10,11} 相同，僅比對集合會漏掉；須另檢長度。"""
        with pytest.raises(AppError) as exc:
            ensure_item_reorder_complete(current_ids={10, 11}, requested=[10, 10, 11])
        assert exc.value.error_code == "ET_ITEM_002"

    def test_空章節送空陣列通過(self) -> None:
        ensure_item_reorder_complete(current_ids=set(), requested=[])

    def test_錯誤碼與章節重排不同(self) -> None:
        """兩層重排須以 error_code 區辨——共用單一代碼會使前端無從分辨是哪一層失敗。"""
        from app.et.course.rules import ensure_reorder_complete as chapter_rule

        with pytest.raises(AppError) as item_exc:
            ensure_item_reorder_complete(current_ids={1}, requested=[])
        with pytest.raises(AppError) as chapter_exc:
            chapter_rule(current_ids={1}, requested=[])
        assert item_exc.value.error_code != chapter_exc.value.error_code


class TestEnsureClosable:
    """僅已發布課程可關閉（US11 AC 2 / FR-ET-US11-01）。"""

    def test_已發布課程可關閉(self) -> None:
        ensure_closable(COURSE_PUBLISHED)

    def test_草稿課程不可關閉(self) -> None:
        """草稿沒有學員、沒有邀請碼，關閉它沒有語意——要移除草稿走既有 DELETE。"""
        with pytest.raises(AppError) as exc:
            ensure_closable(COURSE_DRAFT)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_COURSE_006"

    def test_已關閉課程不可再關閉(self) -> None:
        with pytest.raises(AppError) as exc:
            ensure_closable(COURSE_CLOSED)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_COURSE_006"


class TestEnsureReopenable:
    """僅已關閉課程可再開課（US11 AC 8）。"""

    def test_已關閉課程可再開課(self) -> None:
        ensure_reopenable(COURSE_CLOSED)

    @pytest.mark.parametrize("status", [COURSE_DRAFT, COURSE_PUBLISHED])
    def test_非已關閉不可再開課(self, status: str) -> None:
        """與 `ensure_closable` **分開兩個錯誤碼**：兩者的下一步不同（去發布 / 去再開課）。"""
        with pytest.raises(AppError) as exc:
            ensure_reopenable(status)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ET_COURSE_007"


class TestEnsureReopenSchedule:
    """再開課的新訖止時間須晚於當下（SA Q3 裁示 A）。"""

    def test_未來的訖止時間通過(self) -> None:
        ensure_reopen_schedule(open_end_at=_NOW + timedelta(days=30), now=_NOW)

    def test_已過的訖止時間被擋(self) -> None:
        """否則再開課當下課程又立刻符合「期間已過」——狀態自相矛盾（已發布卻進不去）。"""
        with pytest.raises(AppError) as exc:
            ensure_reopen_schedule(open_end_at=_NOW - timedelta(seconds=1), now=_NOW)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "ET_COURSE_008"

    def test_恰好等於當下被擋(self) -> None:
        """邊界取「須嚴格晚於」——等於當下代表期間在這一瞬間結束，開了也沒有時間可用。"""
        with pytest.raises(AppError) as exc:
            ensure_reopen_schedule(open_end_at=_NOW, now=_NOW)
        assert exc.value.error_code == "ET_COURSE_008"

    def test_不檢核起始時間(self) -> None:
        """裁示 A 只要求檢核訖止。

        起始時間允許落在過去——「補開一段已經開始的期間」是合理操作（教師想讓學員
        從上週就能看）。這也與 2026-08-24 裁示（起始不對比當下）方向一致。
        """
        ensure_reopen_schedule(open_end_at=_NOW + timedelta(days=1), now=_NOW)


class TestIsEffectivelyClosed:
    """課程對學員是否視同關閉（#288 SA Q1 裁示 A）。

    `spec_us11` 場景 7 / FR-ET-US11-03 與 `data-model` §ET_COURSE 業務規則都要求
    「`now > OPEN_END_AT` 視同關閉」，而在本 issue 之前**全後端沒有任何地方讀
    `OPEN_END_AT` 做存取判定**。
    """

    def test_已關閉為視同關閉(self) -> None:
        assert is_effectively_closed(status=COURSE_CLOSED, open_end_at=_NOW + timedelta(days=1), now=_NOW)

    def test_已發布且期間已過為視同關閉(self) -> None:
        """🔴 本函式存在的唯一理由。此前這種課程「照常運作」——可加入、可作答、可填問卷。"""
        assert is_effectively_closed(status=COURSE_PUBLISHED, open_end_at=_NOW - timedelta(seconds=1), now=_NOW)

    def test_恰好等於訖止時間尚未視同關閉(self) -> None:
        """spec 寫「`now > OPEN_END_AT` 視同關閉」——嚴格大於，等於的那一瞬間還在期間內。"""
        assert not is_effectively_closed(status=COURSE_PUBLISHED, open_end_at=_NOW, now=_NOW)

    def test_已發布且期間內不視同關閉(self) -> None:
        assert not is_effectively_closed(status=COURSE_PUBLISHED, open_end_at=_NOW + timedelta(days=1), now=_NOW)

    def test_草稿不視同關閉(self) -> None:
        """🔴 草稿不是「關閉」。

        `learning` 以本函式驅動「此課程目前關閉中」的唯讀提示；把草稿判成關閉，教師
        預覽自己的草稿課程時會看到一句與事實不符的提示。
        """
        assert not is_effectively_closed(status=COURSE_DRAFT, open_end_at=_NOW - timedelta(days=1), now=_NOW)

    def test_訖止為空不視同關閉(self) -> None:
        """為空代表「沒有結束日」——不該因為一個缺失的欄位去關掉一門教師沒有要求關閉的課。

        已發布課程必有起訖（發布檢核 `BLOCK_NO_SCHEDULE`），為空即資料異常。與
        `open_start_at` 的保守方向相反是刻意的：那一半由
        `publish_rules.is_visible_to_student` 承載，本函式不重複它。
        """
        assert not is_effectively_closed(status=COURSE_PUBLISHED, open_end_at=None, now=_NOW)

    def test_不看起始時間(self) -> None:
        """🔴 本函式**只看訖止**，這是為了不推翻 #247 SA Q2 裁示 A。

        那條裁示明訂「起始時間未到之課程**仍可加入**」。若本函式要求「起始已到」，
        `ensure_course_joinable` 會開始擋下起始前的加入，直接違反該裁示——而那個違反
        不會有任何測試抓到，因為 #247 的測試驗的是「可加入」而非「本函式回什麼」。

        本函式的簽章刻意**不收 `open_start_at`**，讓那個錯誤在型別層就寫不出來。
        """
        import inspect

        assert "open_start_at" not in inspect.signature(is_effectively_closed).parameters
