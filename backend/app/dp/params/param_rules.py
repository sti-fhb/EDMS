"""平台級參數型別 / 值域驗證規則（FR-DP-US5-03 落地）。

主檔為種子固定集、維護 UI 不新增主檔，故驗證規則以本模組 registry 按
(PARAM_ID, PARAM_KEY) 維護（非存 DP_PARAM_M 欄位）。見 spec_us5 §參數型別 / 值域驗證規則。
本模組的 `_RULES` 僅涵蓋**平台級** VALUE 參數；模組級（`ET_` / `DM_`）值域由各模組定義，
經 `core/module_param_rules` 的註冊表提供（#528 落地；在那之前「由各模組定義」是一張沒有
兌現的支票——兩側都沒有實作，等於完全不檢核）。

⚠️ **兩處皆查無規則時為 fail-closed（403 DP_PARAM_008），不是略過。** 新增可編輯的 VALUE
參數時必須一併給值域，否則它在 DP03 上會是不可編輯的。
"""

from app.core.exceptions import AppError
from app.core.module_param_rules import IntRule, module_param_rule_registry

_INVALID_MSG = "參數值不合法，請確認格式與值域"
_NO_RULE_MSG = "此參數尚未定義值域規則，不可於畫面修改"


# (PARAM_ID, PARAM_KEY) → 規則。僅平台級 VALUE 參數；模組級的在 module_param_rule_registry。
# ⚠️ 未列於本表**也未由模組註冊**者，validate_param_value 會拒絕編輯（403 DP_PARAM_008），
# 不是略過——新增可編輯的平台級 VALUE 參數時必須在此補一列。
_RULES: dict[tuple[str, str], IntRule] = {
    ("JWT", "ACCESS_TTL_MIN"): IntRule(1, 15),
    ("JWT", "RENEW_MAX_HOURS"): IntRule(1, 24),
    ("PWD_POLICY", "MIN_LEN"): IntRule(8),
    # 上限 72 是**推導的、不是訂的**：password_policy 先查 len(password) < min_length（字元數，
    # DP_PWD_001）再查 len(password.encode()) > _MAX_PASSWORD_BYTES（= 72，bcrypt 截斷上限，
    # DP_PWD_004）。設 73 時 72 字元的被前者擋、73 字元的被後者擋，**沒有任何密碼能同時通過**，
    # 管理者從此設不了密碼。非 ASCII 更早撞牆（一個中文字 3 bytes）。
    # 因跨欄位 ADMIN_MIN_LEN >= MIN_LEN，封這條會連帶壓住 MIN_LEN，故 MIN_LEN 不另設上限。
    ("PWD_POLICY", "ADMIN_MIN_LEN"): IntRule(8, 72),
    ("PWD_POLICY", "CHAR_TYPES"): IntRule(1, 4),
    ("PWD_POLICY", "HISTORY_COUNT"): IntRule(0, 24),
    ("PWD_POLICY", "EXPIRY_DAYS"): IntRule(1, 90),
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS"): IntRule(1),
    # 上限擋的是「設大」：user/service.py 讀此值當鎖定門檻（遞增後計數達此值即鎖定），設成
    # 1000000 等於登入失敗鎖定永遠觸發不到，而 DP03 畫面上只是一個數字變大、無任何警告。
    # 上限 10 取自 spec_us5 平台級參數表該列的「建議 3–10」，下限則留在同列「值域」欄的 ≥ 1——
    # 由該表下註記「『建議』值域為 SD 實作之 sanity guard 上限；型別 / 下限 / 跨欄位規則為硬性
    # 檢核」推得（註記指派兩端的來源，未直接訂下限值）。別「順手補齊」成 IntRule(3, 10)：
    # test_dp_param_rules 的 valid "1" / "2" 即為釘住此決定而設。
    ("LOGIN", "FAIL_LOCK_COUNT"): IntRule(1, 10),
    # 上限擋的是「設大即關掉這道控制」（#528 裁示值，已同步 spec_us5 值域欄）：
    #   LOCK_MINUTES 設大 → 帳號鎖定後解不開，而管理者自己也可能被鎖（DM 側無 bootstrap
    #     管理者機制），24 小時之後就只剩手動解鎖一條路。
    #   RESET_TOKEN_TTL_MIN / EMAIL_CHANGE_TTL_MIN 設大 → 連結近乎永久有效。這兩條與 #50
    #     互鎖：該 issue 指出 DP_EMAIL_LOG.BODY 永久保存含明文重設連結的信件內文，而目前
    #     唯一的緩解就是「一次性 + 短 TTL」——上限放寬等於把那個緩解拆掉，故取 2 小時
    #     （相對預設 30 分鐘仍有 4 倍餘裕）而非業界常見的 24 小時。
    #   IDLE_DISABLE_DAYS 設大 → 閒置帳號永不停用；超過一年還不停用，這道控制等於不存在。
    ("LOGIN", "LOCK_MINUTES"): IntRule(1, 1440),
    ("LOGIN", "RESET_TOKEN_TTL_MIN"): IntRule(1, 120),
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): IntRule(1, 120),
    ("LOGIN", "IDLE_DISABLE_DAYS"): IntRule(1, 365),
    ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC"): IntRule(60, 3600),
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
    """驗證單一 VALUE 參數值之型別 / 值域。

    規則來源有二：平台級查本模組 `_RULES`；模組級（`ET_` / `DM_`）查
    `module_param_rule_registry`——值域屬各模組的業務規則，由模組於 bootstrap 註冊，
    DP 不認識模組語彙（`sti-backend-boundaries`）。

    兩處皆查無時 **fail-closed 拒絕編輯**（#528 裁示 1），不是放行。放行是本 issue 要修的
    缺口本身：日後新增一個可編輯的 VALUE 參數卻忘了給值域，沒有任何跡象；拒絕則立刻現形。
    今日不會誤傷任何參數——17 個平台級全在 `_RULES`，2 個可編輯的模組級由各自 bootstrap
    註冊，其餘模組級參數為 `HIDDEN`、早在 `is_editable_scope` 就被擋下（403 DP_PARAM_007），
    根本進不到這裡。

    Raises:
        AppError: 型別或值域不符（422 DP_PARAM_001）、查無值域規則（403 DP_PARAM_008）。
    """
    rule = _RULES.get((param_id, param_key))
    if rule is None:
        rule = module_param_rule_registry.get(param_id, param_key)
    if rule is None:
        raise AppError(status_code=403, detail=_NO_RULE_MSG, error_code="DP_PARAM_008")
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
