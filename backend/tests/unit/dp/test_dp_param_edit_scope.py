"""維護層級（EDIT_SCOPE）之判定方向（#171）。

判定寫成「只有 ADMIN 可編輯」而非「READONLY / HIDDEN 要擋」。兩者對已知的三個值完全等價，
對**未知值**方向相反：前者擋下、後者放行。

**未知值今天進不了資料庫**——`CK_DP_PARAM_D_EDIT_SCOPE` 擋住非三值之寫入（含決策 2 所指的
「IT 直接操作 DB」那條途徑）。本檔要防的不是那個約束下的現況，而是**程式不要依賴那個約束
存在**：日後若有人加第四個層級、或於未帶約束的環境還原資料，這個方向決定了未知值是變成
「不可編輯」還是「可編輯且畫面看不出異狀」。

一行之差、無額外分支，代價僅此測試。也因為約束擋得住，這條在 integration 層驗不到
（實測：從 DB 寫入非三值會被拒）。
"""

from typing import get_args

import pytest

from app.dp.params.service import EDIT_SCOPE_ADMIN, EDIT_SCOPE_HIDDEN, is_editable_scope

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


def test_every_declared_scope_is_covered():
    """三個具名常數與 schema 的 EditScope 值域一致——新增層級時本條會紅，提醒去看判定方向。"""
    from app.dp.params.schemas import EditScope

    assert set(get_args(EditScope)) == {EDIT_SCOPE_ADMIN, "READONLY", EDIT_SCOPE_HIDDEN}
