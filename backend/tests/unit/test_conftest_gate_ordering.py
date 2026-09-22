"""integration conftest 的 fixture 順序契約（#367）。

## 為什麼這條護欄是**結構性**的而不是行為性的

#367 的症狀只在「該 pytest session 的**第一條**後台測試」上現形——第二條起 `main`
已在 `sys.modules`，`import` 成為 no-op，缺陷自動消失。所以**在整批測試裡寫一條行為
測試抓不到它**：不論修好與否，它在完整跑時都會綠。

唯一能在整批跑裡站得住的護欄，是驗「順序由相依宣告保證」這件事本身。真正的行為驗證
（單獨跑一條後台測試回 200）只能靠獨立的 pytest session，屬 AC 1 的手動驗收範圍。
"""

import inspect

import pytest

pytestmark = pytest.mark.unit


def _fixture_signature(fixture) -> inspect.Signature:
    """取 fixture 底層函式的簽章。

    ⚠️ pytest 用 `FixtureFunctionDefinition` 包住原函式，取法隨版本變動過：舊版可用
    `__wrapped__`，本專案（pytest 9）要用 `_get_wrapped_function()`。兩者皆為私有 API，
    故逐層 fallback——**若 pytest 升版後這裡壞掉，那是取法過期，不是契約被破壞**。
    """
    fn = getattr(fixture, "_get_wrapped_function", lambda: None)() or getattr(fixture, "__wrapped__", fixture)
    return inspect.signature(fn)


def test_backoffice_admin_以相依宣告保證晚於_main_的模組層註冊():
    """`backoffice_admin` 必須宣告 `app_imported`（#367）。

    ⚠️ 拿掉那個參數**目前仍會動**，因為 `app_imported` 是 autouse——所以這條護欄擋的
    不是「會壞」，是「**看不出這裡有順序要求**」。下一個人重構 conftest 時，沒有宣告的
    相依就是不存在的相依。

    順序反過來的後果：`backoffice_admin` 註冊的 always-true checker，會在稍後 `client`
    fixture `import main` 時被 `main.py:179` 的 `register_et_module()` 覆蓋掉，
    使該 session 的第一條後台測試必定 403。
    """
    from tests.integration import conftest

    params = _fixture_signature(conftest.backoffice_admin).parameters

    assert "app_imported" in params, (
        "backoffice_admin 必須宣告 app_imported 相依（#367）——"
        "少了它，順序就只剩 autouse 的巧合，而 conftest 重構時沒人看得出這裡有要求"
    )


def test_app_imported_是_session_級_autouse():
    """`app_imported` 必須是 session-scoped autouse（#367）。

    兩個條件缺一不可：

    - **autouse**：沒有它，只有明確宣告相依的 fixture 受保護，日後新增的 gate 改寫
      fixture 會再踩一次同樣的坑
    - **session scope**：pytest 保證較高 scope 的 autouse fixture 早於 function-scoped
      建立；改成 function scope 就失去這個保證
    """
    from tests.integration import conftest

    marker = conftest.app_imported._fixture_function_marker
    assert marker.scope == "session", f"app_imported 必須是 session scope（現為 {marker.scope}）"
    assert marker.autouse is True, "app_imported 必須 autouse，否則只保護有明確宣告的 fixture"
