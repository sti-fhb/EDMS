"""稽核 CSV 匯出純函式單元測試（欄位中文化 / 未知碼 fallback / 注入防護）。"""

from datetime import datetime, timezone

import pytest

from app.dp.audit.query_service import _csv_cell
from app.dp.audit.schemas import AuditLogResponse

pytestmark = pytest.mark.unit


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
    #322 為 ET03 具名個資匯出新增了 `EXPORT` 後，本測試就從「驗 fallback」默默變成
    「驗中文化」而失敗——拿看起來合理的真實字串當「未知」的樣本，等於賭它永遠不會被
    實作。新增碼時請改補進 `test_csv_action_type_中文化` 的參數表，不要動這裡的樣本。
    """
    assert _csv_cell(_resp(action_type="NOT_A_REAL_ACTION"), "action_type") == "NOT_A_REAL_ACTION"
    assert _csv_cell(_resp(result="NOT_A_REAL_RESULT"), "result") == "NOT_A_REAL_RESULT"


def test_csv_其他欄位不受中文化影響() -> None:
    resp = _resp()
    assert _csv_cell(resp, "created_date") == "2026-07-06 09:15:22"
    assert _csv_cell(resp, "func_label") == "DP-使用者管理"
    assert _csv_cell(resp, "operator_account") == "chen@edms.local"
