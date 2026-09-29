"""維護層級（EDIT_SCOPE）之判定方向（#171）。

判定寫成「只有 ADMIN 可編輯」而非「READONLY / HIDDEN 要擋」，兩者對已知的三個值等價，
但對**未知值**方向相反：前者擋下、後者放行。決策 2 指定 READONLY / HIDDEN 之變更途徑為
「IT 直接操作 DB」，人手寫入就有打成 'readonly' / 'Readonly' 的可能——那一刻兩種寫法
一個讓參數維持不可改、另一個讓它變成可編輯而沒有任何提示。

DB 端另有 `CK_DP_PARAM_D_EDIT_SCOPE` 擋住非三值之寫入，故本檔驗的是「約束萬一不在時
服務層仍朝看得見的方向倒」——也因為約束擋得住，這條在 integration 層驗不到。
"""

import pytest

from app.dp.params.service import EDIT_SCOPE_ADMIN, is_editable_scope

pytestmark = pytest.mark.unit


def test_only_admin_is_editable():
    assert is_editable_scope(EDIT_SCOPE_ADMIN) is True


@pytest.mark.parametrize("scope", ["READONLY", "HIDDEN"])
def test_declared_locked_scopes_are_not_editable(scope):
    assert is_editable_scope(scope) is False


@pytest.mark.parametrize(
    "scope",
    ["readonly", "Admin", "ADMIN ", "", "UNKNOWN"],
    ids=["小寫", "大小寫混雜", "尾端空白", "空字串", "未定義值"],
)
def test_unrecognised_scope_is_not_editable(scope):
    """未知值一律不可編輯（fail-closed）。

    反向寫法（`scope in ("READONLY", "HIDDEN")` 才擋）會讓以上每一個值都變成可編輯，
    且因為參數本來就長得正常，畫面上看不出任何異狀。
    """
    assert is_editable_scope(scope) is False
