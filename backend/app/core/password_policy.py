"""密碼策略工具（T016）。

雜湊採 bcrypt（passlib），複雜度 / 效期 / 歷史門檻皆讀平台級 PWD_POLICY 參數
（research §11），由呼叫方傳入本模組——本模組保持純函式、不依賴 DB / 參數服務。
特權門檻（一般 8 / 特權 12 字元）於變更當下依 is_module_admin() 決定 min_length（T017 / 變更 US）。
"""

from datetime import datetime, timedelta

from passlib.context import CryptContext

from app.core.exceptions import AppError
from app.core.utils import utcnow

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt 僅雜湊前 72 bytes、超過部分靜默截斷（兩個共用前 72 bytes 的不同密碼會驗證通過）；
# 主動擋下超長密碼，避免截斷造成的強度弱化與混淆。
_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """以 bcrypt 雜湊密碼（含隨機 salt）。

    自我強制 72-byte 上限（不變量），使任何呼叫路徑即便未先 validate 亦不會觸發
    bcrypt 靜默截斷，避免防線依賴呼叫方順序。

    Args:
        plain: 明文密碼。

    Returns:
        bcrypt 雜湊字串。

    Raises:
        AppError: 密碼超過 bcrypt 上限（422 / DP_PWD_004）。
    """
    if len(plain.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise AppError(status_code=422, detail="密碼長度超過上限", error_code="DP_PWD_004")
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """驗證明文密碼與 bcrypt 雜湊是否相符。

    Args:
        plain: 待驗證的明文密碼。
        hashed: 既有的 bcrypt 雜湊。

    Returns:
        相符回 True。
    """
    return _pwd_context.verify(plain, hashed)


def _char_type_count(password: str) -> int:
    """計算密碼涵蓋的字元類型數（小寫 / 大寫 / 數字 / 特殊，各計一種）。"""
    types = 0
    if any(c.islower() for c in password):
        types += 1
    if any(c.isupper() for c in password):
        types += 1
    if any(c.isdigit() for c in password):
        types += 1
    # 空白不計為特殊字元（避免以空白灌水通過複雜度門檻）
    if any(not c.isalnum() and not c.isspace() for c in password):
        types += 1
    return types


def validate_password_strength(password: str, *, min_length: int, required_char_types: int = 3) -> None:
    """檢核密碼強度；不符即拋 AppError。

    Args:
        password: 待檢核的明文密碼。
        min_length: 最小長度（字元數，PWD_POLICY MIN_LEN / ADMIN_MIN_LEN，特權由呼叫方判定後傳入）。
        required_char_types: 需涵蓋的字元類型數（PWD_POLICY CHAR_TYPES，預設 3）。

    Raises:
        AppError: 長度不足（422 / DP_PWD_001）、超過 bcrypt 上限（422 / DP_PWD_004）
            或字元類型不足（422 / DP_PWD_002）。
    """
    if len(password) < min_length:
        raise AppError(status_code=422, detail="密碼長度不足", error_code="DP_PWD_001")
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise AppError(status_code=422, detail="密碼長度超過上限", error_code="DP_PWD_004")
    if _char_type_count(password) < required_char_types:
        raise AppError(status_code=422, detail="密碼複雜度不足", error_code="DP_PWD_002")


def is_password_expired(pwd_changed_date: datetime, expiry_days: int, *, now: datetime | None = None) -> bool:
    """判定密碼是否已逾效期。

    Args:
        pwd_changed_date: 上次密碼變更時間（aware datetime）。
        expiry_days: 效期天數（PWD_POLICY EXPIRY_DAYS）；<= 0 視為停用效期、永不過期。
        now: 目前時間；預設 utcnow()，測試可注入。

    Returns:
        已逾效期回 True。
    """
    if expiry_days <= 0:
        return False
    current = now if now is not None else utcnow()
    return current - pwd_changed_date >= timedelta(days=expiry_days)


def is_reused(password: str, recent_hashes: list[str]) -> bool:
    """檢查密碼是否與最近使用過的任一雜湊相符（防重用）。

    Args:
        password: 待檢核的明文密碼。
        recent_hashes: 最近 N 筆 bcrypt 雜湊（呼叫方自 DP_PWD_HIST 取最近 HISTORY_COUNT 筆）。

    Returns:
        命中任一筆回 True。
    """
    return any(verify_password(password, h) for h in recent_hashes)
