"""送檔回應的快取指示覆蓋掃描（#587）。

## 為什麼需要這支測試

檔案回應若不帶 `Cache-Control`，瀏覽器會套用**啟發式快取**（RFC 9111 §4.2.2）並自行
推測新鮮期——`FileResponse` 會自動帶 `Last-Modified` / `ETag`，正好餵給它推測。而
**HTTP 快取的鍵是 URL、不是使用者**：本專案的送檔端點（影片除外）靠 `Authorization`
header 區分身分，URL 對所有人完全相同，於是

- 共用電腦上 A 取過的檔會被快取，B 按下載**請求不送達伺服器**，拿到 A 的內容
- `dm/detail` 那支因此**不執行 `write_read`** → DM06 閱讀率系統性低報

2026-10-12 於部署環境實測：同一位使用者、同一個 URL、同一版本，瀏覽器下載不計入、
API 下載計入；DevTools 顯示 `200 OK (from disk cache)`。

這是 #441（`index.html` 缺 `Cache-Control`）**同一類缺陷的第二次**——那次只修了
`index.html`、沒有盤點其他回應。本檔的目的是讓第三次不會發生。

## 偵測方式：掃 AST 的呼叫，不看回傳型別標註

早一版以 `-> FileResponse` 的回傳標註判定端點，**那是失敗時靜默放行的偵測**：
`from __future__ import annotations` 會讓標註變成字串、標成 `-> Response` 而實際回
`FileResponse` 也抓不到、Union / Annotated 包裝同樣失效，而「漏標註」與「漏設標頭」
正是同一個人在同一刻會一起犯的疏忽。

改為直接掃 `app/` 下每一個 `FileResponse(...)` 呼叫，斷言它帶 `NO_STORE_HEADERS`。
這驗的是**我們真正在意的事**（標頭有沒有設），而非代理指標（端點有沒有登記）。
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: 掃描範圍：後端應用程式碼。
_APP_ROOT = Path(__file__).resolve().parents[2] / "app"

#: 判準常數名。送檔回應必須帶它——理由見 `app/core/http_cache.py` 的 docstring。
_HEADERS_CONST = "NO_STORE_HEADERS"

#: 會送出檔案實體的 response 類別。新增同類時請一併加入。
_FILE_RESPONSE_NAMES = {"FileResponse", "StreamingResponse"}

#: 現有送檔呼叫數的下限。偵測機制壞掉（掃不到任何呼叫）時，若只斷言「沒有違規」
#: 會恆真——這條確保掃描器自身是活的。數量只增不減時調高即可。
_MIN_EXPECTED_CALLS = 5


def _file_response_calls() -> list[tuple[str, int, bool]]:
    """掃出 `app/` 下所有送檔呼叫，回 `(相對路徑, 行號, 是否帶 NO_STORE_HEADERS)`。"""
    results: list[tuple[str, int, bool]] = []
    for py in sorted(_APP_ROOT.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in _FILE_RESPONSE_NAMES:
                continue
            rel = py.relative_to(_APP_ROOT.parent).as_posix()
            results.append((rel, node.lineno, _passes_no_store(node)))
    return results


def _passes_no_store(call: ast.Call) -> bool:
    """`headers=` 是否為 `NO_STORE_HEADERS`，或展開了它的 dict（`{**NO_STORE_HEADERS, ...}`）。"""
    for kw in call.keywords:
        if kw.arg != "headers":
            continue
        value = kw.value
        if isinstance(value, ast.Name) and value.id == _HEADERS_CONST:
            return True
        if isinstance(value, ast.Dict):
            # `{**X, ...}` 在 AST 中是 key=None 的項目
            return any(
                k is None and isinstance(v, ast.Name) and v.id == _HEADERS_CONST
                for k, v in zip(value.keys, value.values, strict=True)
            )
    return False


def test_每個送檔呼叫都必須帶_no_store_標頭():
    """漏設標頭 → 紅，並指名檔案與行號。

    ⚠️ 本條**不檢查**標頭的值字面，只檢查有沒有引用 `NO_STORE_HEADERS`；值本身由
    `app/core/http_cache.py` 單一出處保證，並由 integration 測試實際斷言回應內容
    （`test_dm_detail.py` / `test_dm_obsolete_flow.py`）。
    """
    calls = _file_response_calls()

    # 掃描器自身的健康檢查：抓不到呼叫 ⇒ AST 走訪或路徑壞了，而非真的沒有送檔端點
    assert len(calls) >= _MIN_EXPECTED_CALLS, (
        f"只掃到 {len(calls)} 個送檔呼叫（預期至少 {_MIN_EXPECTED_CALLS}）——"
        "`_file_response_calls` 或 `_APP_ROOT` 可能已失效"
    )

    offenders = [(path, line) for path, line, ok in calls if not ok]
    assert not offenders, (
        "以下送檔呼叫未帶 `NO_STORE_HEADERS`：\n"
        + "\n".join(f"  {p}:{ln}" for p, ln in offenders)
        + "\n判準見 `app/core/http_cache.py`：回應取決於「誰在問」而 URL 對所有人相同者，"
        "不擋快取會讓第二個人的請求不送達伺服器。"
    )


def test_掃描器抓得到展開寫法():
    """`{**NO_STORE_HEADERS, ...}` 必須被視為合格——ET 影片端點就是這個寫法。

    少了這條，有人把 `_passes_no_store` 簡化成「只認 Name」時，影片端點會被誤判為違規，
    而修法很可能是把它從掃描範圍排除掉（等於開一個永久豁免）。
    """
    spread = ast.parse("FileResponse(p, headers={**NO_STORE_HEADERS, 'X': 'y'})").body[0].value
    plain = ast.parse("FileResponse(p, headers=NO_STORE_HEADERS)").body[0].value
    missing = ast.parse("FileResponse(p)").body[0].value
    other = ast.parse("FileResponse(p, headers={'Cache-Control': 'private, no-store'})").body[0].value

    assert _passes_no_store(spread)
    assert _passes_no_store(plain)
    assert not _passes_no_store(missing)
    # 字面值不算：判準必須有單一出處，否則下一個人改 http_cache 時不會知道這裡也要改
    assert not _passes_no_store(other)
