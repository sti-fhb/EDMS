"""US5 參數型別 / 值域驗證規則單元測試（param_rules，不連 DB）。"""

import pytest

from app.core.exceptions import AppError
from app.dp.params.param_rules import validate_group_invariants, validate_param_value

pytestmark = pytest.mark.unit


# ---- 單值型別 / 值域（AC2/6）----


@pytest.mark.parametrize(
    ("param_id", "param_key", "value"),
    [
        ("JWT", "ACCESS_TTL_MIN", "15"),  # 上限邊界
        ("JWT", "ACCESS_TTL_MIN", "1"),  # 下限邊界
        ("PWD_POLICY", "MIN_LEN", "8"),  # 僅下限
        ("PWD_POLICY", "CHAR_TYPES", "4"),
        ("MAIL", "RETRY_MAX", "0"),  # 非負下限
        ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC", "600"),  # 冷卻秒數（60–3600）
        # FAIL_LOCK_COUNT 值域 1–10（#454）。"1" 與 "2" 釘的是**下限留在 1**：spec 的
        # 「建議 3–10」只供上限，下限以「值域」欄的 ≥ 1 為準（理由見 param_rules 該列註解）。
        # 這兩條在本次修改前後都是綠的——它們防的是日後有人把規則「補齊」成 IntRule(3, 10)。
        ("LOGIN", "FAIL_LOCK_COUNT", "1"),
        ("LOGIN", "FAIL_LOCK_COUNT", "2"),
        ("LOGIN", "FAIL_LOCK_COUNT", "3"),  # 建議區間下緣
        ("LOGIN", "FAIL_LOCK_COUNT", "5"),  # 種子預設值
        ("LOGIN", "FAIL_LOCK_COUNT", "10"),  # 上限邊界
    ],
)
def test_valid_values_pass(param_id, param_key, value):
    validate_param_value(param_id, param_key, value)  # 不拋即通過


@pytest.mark.parametrize(
    ("param_id", "param_key", "value"),
    [
        ("JWT", "ACCESS_TTL_MIN", "16"),  # 超上限（>15）
        ("JWT", "ACCESS_TTL_MIN", "0"),  # 低於下限
        ("PWD_POLICY", "MIN_LEN", "7"),  # 低於 8
        ("PWD_POLICY", "CHAR_TYPES", "5"),  # 超過 4
        ("PWD_POLICY", "EXPIRY_DAYS", "91"),  # 超過 90
        ("JWT", "ACCESS_TTL_MIN", "abc"),  # 非整數
        ("JWT", "ACCESS_TTL_MIN", "15.5"),  # 浮點
        ("MAIL", "RETRY_MAX", "-1"),  # 負數
        ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC", "59"),  # 低於 60
        ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC", "3601"),  # 超過 3600
        ("LOGIN", "FAIL_LOCK_COUNT", "0"),  # 低於下限 1；與 valid 的 "1" / "2" 一起把下限兩側都釘住
        ("LOGIN", "FAIL_LOCK_COUNT", "11"),  # 超過 10（#454）
        ("LOGIN", "FAIL_LOCK_COUNT", "1000000"),  # #454 原始情境：設大即實質關閉登入失敗鎖定
    ],
)
def test_invalid_values_raise(param_id, param_key, value):
    with pytest.raises(AppError) as exc:
        validate_param_value(param_id, param_key, value)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_PARAM_001"


def test_unknown_param_skips_check():
    # 未列於 registry（模組級 / 未知）→ 不做值域檢核，不拋
    validate_param_value("ET_SOMETHING", "FOO", "任意值")
    validate_param_value("JWT", "UNKNOWN_KEY", "任意值")


# ---- 跨欄位一致性（PWD_POLICY）----


def test_admin_min_len_must_ge_min_len():
    with pytest.raises(AppError) as exc:
        validate_group_invariants("PWD_POLICY", {"MIN_LEN": "12", "ADMIN_MIN_LEN": "10"})
    assert exc.value.error_code == "DP_PARAM_001"


def test_expiry_remind_must_lt_expiry():
    with pytest.raises(AppError) as exc:
        validate_group_invariants("PWD_POLICY", {"EXPIRY_DAYS": "90", "EXPIRY_REMIND_DAYS": "90"})
    assert exc.value.error_code == "DP_PARAM_001"


def test_group_invariants_pass_and_tolerate_missing():
    # 合法組合不拋
    validate_group_invariants(
        "PWD_POLICY", {"MIN_LEN": "8", "ADMIN_MIN_LEN": "12", "EXPIRY_DAYS": "90", "EXPIRY_REMIND_DAYS": "7"}
    )
    # 非 PWD_POLICY 群組略過
    validate_group_invariants("JWT", {"ACCESS_TTL_MIN": "15"})
    # 缺值不誤判
    validate_group_invariants("PWD_POLICY", {"MIN_LEN": "8"})
