"""稽核 CSV 匯出純函式單元測試（欄位中文化 / 未知碼 fallback / 注入防護 / 時區）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.dp.audit.query_service import _csv_cell
from app.dp.audit.router import _export_filename
from app.dp.audit.schemas import AuditLogResponse

pytestmark = pytest.mark.unit

#: 台灣 2026-10-01 07:30:45（UTC 為前一日 23:30:45）。
#: 刻意落在**台灣 00:00–08:00**：只有這 8 小時內 UTC 與台灣才跨日，取中午的時點會讓
#: 「有換算」與「沒換算」輸出同一個日期，測試即失去鑑別力（#519）。
_CROSS_DAY_UTC = datetime(2026, 9, 30, 23, 30, 45, tzinfo=timezone.utc)


def _resp(**overrides) -> AuditLogResponse:
    base = {
        "log_id": 1,
        "created_date": datetime(2026, 7, 6, 9, 15, 22, tzinfo=timezone.utc),
        "operator_id": "u001",
        "operator_name": "陳大華",
        "operator_email": "chen@edms.local",
        "module": "DP",
        "func_name": "DP-USERS",
        "func_label": "DP-使用者管理",
        "action_type": "UPDATE",
        "result": "SUCCESS",
        "target_id": "u1042",
        "target_display": "林小美",
        "source_ip": "10.1.2.33",
        "description": "手動解鎖帳號",
        "before_value": None,
        "after_value": None,
    }
    return AuditLogResponse(**{**base, **overrides})


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("LOGIN", "登入"),
        ("LOGOUT", "登出"),
        ("CREATE", "新增"),
        ("UPDATE", "修改"),
        ("DELETE", "刪除"),
        ("EXPORT", "匯出"),
    ],
)
def test_csv_action_type_中文化(code: str, expected: str) -> None:
    assert _csv_cell(_resp(action_type=code), "action_type") == expected


@pytest.mark.parametrize(("code", "expected"), [("SUCCESS", "成功"), ("FAIL", "失敗")])
def test_csv_result_中文化(code: str, expected: str) -> None:
    assert _csv_cell(_resp(result=code), "result") == expected


def test_csv_未知碼原樣輸出() -> None:
    """對照表查不到的碼原樣輸出，不因查不到而變成空白。

    ⚠️ 樣本刻意用**不可能成為真實碼**的字串。這裡原本寫 `"EXPORT"` / `"PARTIAL"`，而
    #322 為 ET02 具名個資匯出新增了 `EXPORT` 後，本測試就從「驗 fallback」默默變成
    「驗中文化」而失敗——拿看起來合理的真實字串當「未知」的樣本，等於賭它永遠不會被
    實作。新增碼時請改補進 `test_csv_action_type_中文化` 的參數表，不要動這裡的樣本。
    """
    assert _csv_cell(_resp(action_type="NOT_A_REAL_ACTION"), "action_type") == "NOT_A_REAL_ACTION"
    assert _csv_cell(_resp(result="NOT_A_REAL_RESULT"), "result") == "NOT_A_REAL_RESULT"


def test_csv_其他欄位不受中文化影響() -> None:
    """⚠️ `created_date` 的預期值在 #519 由 UTC 改為台灣時間（09:15:22 → 17:15:22）。

    此處樣本是**同日**時點，對時區沒有鑑別力（改與不改都只差時分、不差日期），
    真正守門的是下面兩條跨日測試。這裡保留它只是確認中文化沒有誤傷時間欄。
    """
    resp = _resp()
    assert _csv_cell(resp, "created_date") == "2026-07-06 17:15:22"
    assert _csv_cell(resp, "func_label") == "DP-使用者管理"
    assert _csv_cell(resp, "operator_account") == "chen@edms.local"


def test_csv_操作時間以台灣時間輸出且保留秒() -> None:
    """跨日時點：必須輸出台灣的 10/01 07:30:45，不是 UTC 的 09/30 23:30:45。

    **秒不可省**：稽核匯出是調查證據，降精度到分鐘會讓同一分鐘內的多筆事件失去先後順序。
    故本條同時釘住「換算到台灣」與「保留秒」兩件事——只做前者會輸出 `07:30`，一樣紅。
    """
    taipei = "2026-10-01 07:30:45"
    utc = "2026-09-30 23:30:45"

    assert taipei != utc, "時點設計失誤：兩者相同則本測試無鑑別力"

    rendered = _csv_cell(_resp(created_date=_CROSS_DAY_UTC), "created_date")

    assert rendered == taipei
    assert rendered != utc


def test_csv_操作時間已是台灣時區則不再偏移() -> None:
    """輸入若已帶 +08:00，不應再加一次 8 小時。"""
    taipei_aware = datetime(2026, 10, 1, 7, 30, 45, tzinfo=timezone(timedelta(hours=8)))

    assert _csv_cell(_resp(created_date=taipei_aware), "created_date") == "2026-10-01 07:30:45"


def test_匯出檔名日期以台灣時間計算() -> None:
    """檔名的日期同樣來自 `TIMESTAMPTZ` 語意的當下時間，台灣 00:00–08:00 匯出不該命名成前一天。"""
    taipei = "audit_log_20261001.csv"
    utc = "audit_log_20260930.csv"

    assert taipei != utc, "時點設計失誤：兩者相同則本測試無鑑別力"

    assert _export_filename(_CROSS_DAY_UTC) == taipei
