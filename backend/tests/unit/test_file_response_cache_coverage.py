"""送檔回應的快取指示覆蓋掃描（#587）。

## 為什麼需要這支測試

檔案回應若不帶 `Cache-Control`，瀏覽器私有快取可自行推測新鮮期（RFC 9111 §4.2.2）
——`FileResponse` 會自動帶 `Last-Modified` / `ETag`，等於親手把 validator 交出去。而
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

#: 永遠送出檔案實體的 response 類別。
_ALWAYS_FILE = {"FileResponse", "StreamingResponse"}

#: 現有送檔呼叫數的下限。偵測機制壞掉（掃不到任何呼叫）時，若只斷言「沒有違規」
#: 會恆真——這條確保掃描器自身是活的。
#: ⚠️ 刪除送檔端點時要一併下修，否則會紅在一個無辜的地方。
_MIN_EXPECTED_CALLS = 12


def _local_aliases(tree: ast.AST) -> set[str]:
    """本檔對送檔類別的別名（`from ... import FileResponse as FR`）。

    少了這層，`FR(...)` 會完全掃不到。機率低，但偵測漏掉等於靜默放行。
    """
    names = set(_ALWAYS_FILE)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name in _ALWAYS_FILE and a.asname:
                    names.add(a.asname)
    return names


def _is_download_response(call: ast.Call, name: str, file_names: set[str]) -> bool:
    """這個呼叫是否送出「檔案式」回應。

    兩種形狀：

    1. `FileResponse` / `StreamingResponse`（或其別名）——恆是。
    2. 純 `Response(...)` 但帶 `Content-Disposition: attachment` 或 CSV media_type
       ——七支匯出端點即此形狀。**不能只掃 `FileResponse`**：判準講的是「權限相依且
       URL 對所有人相同」，CSV 匯出精準命中它，漏掉的話判準承諾的範圍會大於守門
       實際覆蓋的範圍，而那份落差正是下一次漏接的來源。
    """
    if name in file_names:
        return True
    if name != "Response":
        return False
    for kw in call.keywords:
        if kw.arg == "media_type" and isinstance(kw.value, ast.Constant) and "csv" in str(kw.value.value):
            return True
        if kw.arg == "headers" and isinstance(kw.value, ast.Dict):
            for k in kw.value.keys:
                if isinstance(k, ast.Constant) and str(k.value).lower() == "content-disposition":
                    return True
    return False


def _download_response_calls() -> list[tuple[str, int, bool]]:
    """掃出 `app/` 下所有檔案式回應，回 `(相對路徑, 行號, 是否帶 NO_STORE_HEADERS)`。"""
    results: list[tuple[str, int, bool]] = []
    for py in sorted(_APP_ROOT.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        file_names = _local_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if not name or not _is_download_response(node, name, file_names):
                continue
            rel = py.relative_to(_APP_ROOT.parent).as_posix()
            results.append((rel, node.lineno, _passes_no_store(node)))
    return results


def _passes_no_store(call: ast.Call) -> bool:
    """`headers=` 是否確實讓 `NO_STORE_HEADERS` 生效。

    🔴 展開形必須再檢查「後面有沒有字面 `Cache-Control` 把它蓋掉」——
    `{**NO_STORE_HEADERS, "Cache-Control": "public, max-age=86400"}` 送出的是
    `public, max-age=86400`，但只看「有沒有展開」會放行。dict 是後者覆寫前者。
    """
    for kw in call.keywords:
        if kw.arg != "headers":
            continue
        value = kw.value
        if isinstance(value, ast.Name) and value.id == _HEADERS_CONST:
            return True
        if isinstance(value, ast.Dict):
            # `{**X, ...}` 在 AST 中是 key=None 的項目
            spread_at = [
                i
                for i, k in enumerate(value.keys)
                if k is None and isinstance(value.values[i], ast.Name) and value.values[i].id == _HEADERS_CONST
            ]
            if not spread_at:
                return False
            after = value.keys[spread_at[-1] + 1 :]
            return not any(isinstance(k, ast.Constant) and str(k.value).lower() == "cache-control" for k in after)
    return False


def test_每個檔案式回應都必須帶_no_store_標頭():
    """漏設標頭 → 紅，並指名檔案與行號。

    ⚠️ 本條**不檢查**標頭的值字面，只檢查有沒有引用 `NO_STORE_HEADERS`；值本身由
    `app/core/http_cache.py` 單一出處保證，並由 integration 測試實際斷言回應內容
    （`test_dm_detail.py` / `test_dm_obsolete_flow.py`）。
    """
    calls = _download_response_calls()

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
    """`{**NO_STORE_HEADERS, ...}` 合格，但**被字面值蓋掉就不合格**。

    少了這條，有人把 `_passes_no_store` 簡化成「只認 Name」時，影片端點會被誤判為違規，
    而修法很可能是把它從掃描範圍排除掉（等於開一個永久豁免）。
    """
    spread = ast.parse("FileResponse(p, headers={**NO_STORE_HEADERS, 'X': 'y'})").body[0].value
    plain = ast.parse("FileResponse(p, headers=NO_STORE_HEADERS)").body[0].value
    missing = ast.parse("FileResponse(p)").body[0].value
    other = ast.parse("FileResponse(p, headers={'Cache-Control': 'private, no-store'})").body[0].value

    # 🔴 展開後又被字面 Cache-Control 蓋掉——送出的是 public, max-age，必須判為違規
    overridden = (
        ast.parse("FileResponse(p, headers={**NO_STORE_HEADERS, 'Cache-Control': 'public, max-age=1'})").body[0].value
    )

    assert _passes_no_store(spread)
    assert _passes_no_store(plain)
    assert not _passes_no_store(missing)
    # 字面值不算：判準必須有單一出處，否則下一個人改 http_cache 時不會知道這裡也要改
    assert not _passes_no_store(other)
    assert not _passes_no_store(overridden)


def test_CSV_匯出也在掃描範圍內():
    """判準說的是「權限相依且 URL 對所有人相同」，`Response(media_type=csv)` 精準命中。

    只掃 `FileResponse` 會讓七支匯出端點落在守門視野外，而 `http_cache` 的 docstring
    卻宣稱「覆蓋範圍由本檔釘住」——那份落差本身就是下一次漏接的來源。
    """
    csv_call = ast.parse('Response(content=c, media_type="text/csv; charset=utf-8")').body[0].value
    disp_call = ast.parse('Response(content=c, headers={"Content-Disposition": "attachment"})').body[0].value
    json_call = ast.parse('Response(content=c, media_type="application/json")').body[0].value

    names = set(_ALWAYS_FILE)
    assert _is_download_response(csv_call, "Response", names)
    assert _is_download_response(disp_call, "Response", names)
    # 一般 JSON 回應不該被拖進來
    assert not _is_download_response(json_call, "Response", names)
