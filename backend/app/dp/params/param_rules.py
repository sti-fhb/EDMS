"""平台級參數型別 / 值域驗證規則（FR-DP-US5-03 落地）。

主檔為種子固定集、維護 UI 不新增主檔，故驗證規則以本模組 registry 按
(PARAM_ID, PARAM_KEY) 維護（非存 DP_PARAM_M 欄位）。見 spec_us5 §參數型別 / 值域驗證規則。
僅涵蓋平台級 VALUE 參數；模組級（ET_ / DM_）值域由各模組定義，本 registry 未列者不做值域檢核。
"""

from dataclasses import dataclass

from app.core.exceptions import AppError

_INVALID_MSG = "參數值不合法，請確認格式與值域"


@dataclass(frozen=True)
class IntRule:
    """整數型參數值域規則；max_value 為 None 代表無上限（僅型別 + 下限）。"""

    min_value: int
    max_value: int | None = None


# (PARAM_ID, PARAM_KEY) → 規則。僅平台級 VALUE 參數；未列者不做值域檢核（回 None）。
_RULES: dict[tuple[str, str], IntRule] = {
    ("JWT", "ACCESS_TTL_MIN"): IntRule(1, 15),
    ("JWT", "RENEW_MAX_HOURS"): IntRule(1, 24),
    ("PWD_POLICY", "MIN_LEN"): IntRule(8),
    ("PWD_POLICY", "ADMIN_MIN_LEN"): IntRule(8),
    ("PWD_POLICY", "CHAR_TYPES"): IntRule(1, 4),
    ("PWD_POLICY", "HISTORY_COUNT"): IntRule(0, 24),
    ("PWD_POLICY", "EXPIRY_DAYS"): IntRule(1, 90),
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS"): IntRule(1),
    ("LOGIN", "FAIL_LOCK_COUNT"): IntRule(1),
    ("LOGIN", "LOCK_MINUTES"): IntRule(1),
    ("LOGIN", "RESET_TOKEN_TTL_MIN"): IntRule(1),
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): IntRule(1),
    ("LOGIN", "IDLE_DISABLE_DAYS"): IntRule(1),
    ("MAIL", "RATE_PER_MIN"): IntRule(1),
    ("MAIL", "RETRY_MAX"): IntRule(0, 10),
    ("MAIL", "RETRY_INTERVAL_MIN"): IntRule(1),
}


def _invalid() -> AppError:
    return AppError(status_code=422, detail=_INVALID_MSG, error_code="DP_PARAM_001")


def _to_int(raw: str | None) -> int | None:
    """字串轉整數；None / 空字串回 None（供跨欄位檢核容忍缺值）。非整數格式一律拋 DP_PARAM_001。"""
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise _invalid() from exc


def validate_param_value(param_id: str, param_key: str, value: str) -> None:
    """驗證單一 VALUE 參數值之型別 / 值域；未列於 registry 者略過。

    Raises:
        AppError: 型別或值域不符（422 DP_PARAM_001）。
    """
    rule = _RULES.get((param_id, param_key))
    if rule is None:
        return
    num = _to_int(value)
    if num is None:
        raise _invalid()
    if num < rule.min_value or (rule.max_value is not None and num > rule.max_value):
        raise _invalid()


def validate_group_invariants(param_id: str, values: dict[str, str]) -> None:
    """檢核同 PARAM_ID 群組之跨欄位一致性（values＝套用新值後的完整 key→value）。

    僅檢核已知有跨欄位約束的群組（目前 PWD_POLICY）；缺值（None）之欄位略過該條約束。

    Raises:
        AppError: 跨欄位不一致（422 DP_PARAM_001）。
    """
    if param_id != "PWD_POLICY":
        return
    min_len = _to_int(values.get("MIN_LEN"))
    admin_min = _to_int(values.get("ADMIN_MIN_LEN"))
    if min_len is not None and admin_min is not None and admin_min < min_len:
        raise _invalid()
    expiry = _to_int(values.get("EXPIRY_DAYS"))
    remind = _to_int(values.get("EXPIRY_REMIND_DAYS"))
    if expiry is not None and remind is not None and remind >= expiry:
        raise _invalid()
