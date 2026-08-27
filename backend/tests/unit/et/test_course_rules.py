"""ET 課程 / 章節之純業務規則 unit test（#202）。

依 sti-testing「拿掉真 DB 仍驗得了就寫 unit」原則——本檔所驗規則皆為集合與字串運算，
不需 DB。需查 `ET_TAG.IS_ACTIVE`、`ET_PROGRESS` 連帶刪除等真互動者寫 integration。
"""

import pytest

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.rules import (
    ensure_deletable,
    ensure_item_reorder_complete,
    ensure_owner,
    ensure_reorder_complete,
    ensure_tag_change_allowed,
    resequence,
)

pytestmark = pytest.mark.unit


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
