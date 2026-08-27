"""架構護欄：app/ 內不得直接呼叫同步的密碼運算（#214）。

同步 hash_password / verify_password / is_reused 會阻塞 event loop 約 185 ms/次（一次密碼
重設最壞是 4 次）。本測試把「必須改用 password_hashing 的 async 包裝」變成機器可驗證的
約束——比照 #137 的 kind 常數護欄：靠人記得不算保證，日後新端點若照舊寫法複製貼上，
這裡會擋下來。

比對方式用 tokenize 而非正則掃行：只認「NAME token 為三個同步名稱之一、緊接著左括號」
的**實際呼叫**，因此註解與字串常值中提到這些名稱都不會誤判（例如 docstring 寫
「改用 hash_password() 之前」）。純正則版本得自行剔除註解，而以第一個 # 切字串會漏抓
「字串常值內含 # 之後才出現的真違規」。

允許清單以**相對路徑**比對，避免任何目錄下的同名檔案自動獲得豁免：
- core/password_policy.py——同步版的定義處
- core/password_hashing.py——async 包裝，本來就要呼叫同步版

已知限制：本護欄擋「照舊寫法複製貼上」，不擋刻意規避
（例如 from ... import hash_password as _h 再呼叫 _h(...)）。與 #137 的護欄同一限制；
改成完整的 import 別名追蹤成本不划算。
"""

import io
import tokenize
from pathlib import Path

import pytest

import app as app_pkg

pytestmark = pytest.mark.unit

_APP_ROOT = Path(app_pkg.__file__).parent
_ALLOWED = {Path("core/password_policy.py"), Path("core/password_hashing.py")}
_SYNC_NAMES = {"hash_password", "verify_password", "is_reused"}
_SKIP_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
}


def _sync_calls(source: str) -> list[tuple[int, str]]:
    """回傳 (行號, 名稱)：實際呼叫同步密碼函式的位置。註解 / 字串常值不計。"""
    found: list[tuple[int, str]] = []
    previous: tokenize.TokenInfo | None = None
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _SKIP_TOKEN_TYPES:
            continue
        if (
            token.type == tokenize.OP
            and token.string == "("
            and previous is not None
            and previous.type == tokenize.NAME
            and previous.string in _SYNC_NAMES
        ):
            found.append((previous.start[0], previous.string))
        previous = token
    return found


def test_no_sync_password_calls_in_app():
    """除定義處與 async 包裝外，app/ 全域不得出現同步密碼運算的呼叫。"""
    offenders: list[str] = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        relative = path.relative_to(_APP_ROOT)
        if relative in _ALLOWED:
            continue
        for lineno, name in _sync_calls(path.read_text(encoding="utf-8")):
            offenders.append(f"{relative}:{lineno}: {name}(...)")
    assert offenders == [], "發現同步密碼運算呼叫（應改用 password_hashing 的 async 版）:\n" + "\n".join(offenders)


def test_guard_detects_a_real_violation():
    """護欄本身要有牙齒：對「像違規的程式碼」必須抓到，對註解 / 字串必須放行。

    沒有這條，上面那個 assert 可能因為掃描邏輯壞掉而永遠通過（空清單假綠）。
    """
    violating = "def f(user):\n    return verify_password(user.pwd, user.hash)\n"
    assert _sync_calls(violating) == [(2, "verify_password")]

    innocent = (
        "# 舊寫法是 hash_password()，已改用 async 版\n"
        'MSG = "呼叫 is_reused() 前先讀 # 注意事項；不可用 verify_password()"\n'
        "x = 1\n"
    )
    assert _sync_calls(innocent) == []
