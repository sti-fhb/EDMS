"""稽核功能碼（`DP_AUDIT_LOG.FUNC_NAME`）的清單完整性守門（#477）。

`_FUNC_LABELS` 同時決定三件事：操作記錄查詢的「功能」下拉選項、列表的功能欄中文、
CSV 匯出的功能欄中文。漏補一個 `func_name` 的後果是**靜默的**——`_func_label()` 查不到
就原樣回傳原碼，不報錯；下拉少一個選項也不會有人發現。#477 之前就是這樣累積到少 13 項，
其中 `ET-COURSE` 在 dev DB 有 257 筆、是全表第二大。

本檔掃描 `app/` 下所有 `func_name` 的字面值，斷言皆已登錄。

⚠️ **能力界線**：掃描只認得「字面字串」的寫法（常數定義或 `func_name="..."` 直接傳入）。
若日後有人用變數拼接或由設定帶入 `func_name`，本測試**抓不到**——那種寫法本身也會讓
查詢端無從列舉，屆時應先回頭要求改回字面值，而不是放寬這裡。
"""

import re
from pathlib import Path

import pytest

from app.dp.audit.query_service import FUNC_OPTIONS, _FUNC_LABELS

pytestmark = pytest.mark.unit

_APP_DIR = Path(__file__).resolve().parents[3] / "app"

# 兩種字面寫法：模組層常數（`_FUNC_XXX = "DM-EDITOR"`）與呼叫處直接傳入（`func_name="DP-AUTH"`）。
# 常數名不限於 `_FUNC_NAME`——實際存在 `_FUNC_EXPORT` / `_FUNC_RESET` / `_FUNC_NAME_ATTEMPT` 等變體，
# 以 `_FUNC` 開頭一律納入（#477 初次盤點就是因為只比對 `_FUNC_NAME` 而漏掉 4 個 ET 功能）。
_CONST_PATTERN = re.compile(r'^_FUNC[A-Z_]*(?:\s*:\s*[A-Za-z]+)?\s*=\s*"([^"]+)"', re.M)
_INLINE_PATTERN = re.compile(r'func_name\s*=\s*"([^"]+)"')


def _scan_func_names() -> set[str]:
    """掃出 `app/` 下所有以字面值出現的 `func_name`。"""
    found: set[str] = set()
    for path in _APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(_CONST_PATTERN.findall(text))
        found.update(_INLINE_PATTERN.findall(text))
    return found


def test_每個寫入端的功能碼都有對應中文():
    """漏補時本條變紅——這是 #477 唯一會自動發現「新模組寫了稽核卻沒補清單」的機制。"""
    missing = sorted(_scan_func_names() - set(_FUNC_LABELS))
    assert not missing, (
        f"以下 func_name 有寫入端但不在 _FUNC_LABELS，查詢端會少選項、列表與 CSV 會顯示原碼：{missing}"
    )


def test_清單沒有多出不存在的功能碼():
    """反向守門：`_FUNC_LABELS` 列了但沒有任何寫入端的碼，會讓下拉出現永遠查不到資料的選項。"""
    orphans = sorted(set(_FUNC_LABELS) - _scan_func_names())
    assert not orphans, f"以下 func_name 在 _FUNC_LABELS 但無任何寫入端：{orphans}"


def test_掃描本身有抓到東西():
    """守住守門測試自己——掃描若因路徑或正則寫錯而回空集合，上面兩條都會假性通過。"""
    found = _scan_func_names()
    assert len(found) >= 20, f"掃描結果僅 {len(found)} 筆，疑似路徑或正則有誤：{sorted(found)}"
    assert "DP-AUTH" in found  # 常數寫法
    assert "DM-EDITOR" in found  # 呼叫處直接傳入


def test_每個模組前綴都有功能碼():
    """三個模組都要有——ET 曾經整組缺席（#477），而少一個模組不會讓任何既有測試變紅。"""
    prefixes = {code.split("-", 1)[0] for code in _FUNC_LABELS}
    assert {"DP", "ET", "DM"} <= prefixes, f"缺少模組前綴：{ {'DP', 'ET', 'DM'} - prefixes }"


def test_func_options_與_labels_同步():
    """`FUNC_OPTIONS` 是前端下拉的唯一來源，必須完整反映 `_FUNC_LABELS`。"""
    assert [o["value"] for o in FUNC_OPTIONS] == list(_FUNC_LABELS)
    assert all(o["label"] == _FUNC_LABELS[o["value"]] for o in FUNC_OPTIONS)
