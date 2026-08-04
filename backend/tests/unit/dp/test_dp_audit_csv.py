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
    [("LOGIN", "登入"), ("LOGOUT", "登出"), ("CREATE", "新增"), ("UPDATE", "修改"), ("DELETE", "刪除")],
)
def test_csv_action_type_中文化(code: str, expected: str) -> None:
    assert _csv_cell(_resp(action_type=code), "action_type") == expected


@pytest.mark.parametrize(("code", "expected"), [("SUCCESS", "成功"), ("FAIL", "失敗")])
def test_csv_result_中文化(code: str, expected: str) -> None:
    assert _csv_cell(_resp(result=code), "result") == expected


def test_csv_未知碼原樣輸出() -> None:
    assert _csv_cell(_resp(action_type="EXPORT"), "action_type") == "EXPORT"
    assert _csv_cell(_resp(result="PARTIAL"), "result") == "PARTIAL"


def test_csv_其他欄位不受中文化影響() -> None:
    resp = _resp()
    assert _csv_cell(resp, "created_date") == "2026-07-06 09:15:22"
    assert _csv_cell(resp, "func_label") == "DP-使用者管理"
    assert _csv_cell(resp, "operator_account") == "chen@edms.local"
