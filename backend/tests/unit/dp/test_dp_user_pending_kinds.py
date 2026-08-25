"""待驗證列 KIND 值域之單一定義護欄（#137）。

`ADMIN_INVITE` 是**安全不變量**：`register_service` 的「未逾期邀請擋下自助註冊」守衛，
與 `repository.delete_pending_unless_active_invite` 的條件式刪除，必須命中同一字串，
#125 的修補才成立。原本四個檔案各自定義同名私有常數、沒有任何機制保證一致，
本測試把「只有一處定義」變成機器可驗證的約束（比照 ET Foundation 的反向驗證測試作法）。
"""

import re
from pathlib import Path

import pytest

import app as app_pkg
from app.dp.user.kinds import KIND_ADMIN_INVITE, KIND_SELF_REGISTER

pytestmark = pytest.mark.unit

_APP_ROOT = Path(app_pkg.__file__).parent
_KINDS_MODULE = _APP_ROOT / "dp" / "user" / "kinds.py"


def _files_with_literal(value: str) -> list[str]:
    """回傳 backend/app 下（kinds.py 以外）出現該字串**字面量**的檔案清單。

    只比對帶引號的字面量，docstring / 註解中以文字提及（如「僅 ADMIN_INVITE 有值」）不算。
    """
    pattern = re.compile(rf"""["']{re.escape(value)}["']""")
    hits: list[str] = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        if path == _KINDS_MODULE:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(_APP_ROOT)))
    return hits


def test_kind_values_match_db_domain():
    """常數值即 DB 欄位實際值域，改動會讓既有資料判定失效，故明確釘住。"""
    assert KIND_ADMIN_INVITE == "ADMIN_INVITE"
    assert KIND_SELF_REGISTER == "SELF_REGISTER"


def test_admin_invite_literal_defined_only_once():
    """`ADMIN_INVITE` 字面量在 app 內只能出現於 kinds.py（AC：其餘處一律引用）。"""
    assert _files_with_literal("ADMIN_INVITE") == []


def test_self_register_literal_defined_only_once():
    """`SELF_REGISTER` 同樣收斂——同一值域分散定義同樣會漂移。"""
    assert _files_with_literal("SELF_REGISTER") == []
