"""JWT 基礎（T013）。

EDMS 採無狀態簡單對稱 JWT（research §2）：payload 含 sub（USER_ID）、auth_time
（本次登入時間，換發沿用）、iat、exp。**不含角色**（§4，角色即時由模組判定）、
**無 site_id**（單一組織）。短 TTL（閒置逾時）+ 活動換發（單日時數上限）。

TTL / 換發上限值存 DP_PARAM（JWT 參數），由呼叫方以 SRVDP001 讀出後傳入 ttl_minutes /
renew_max_hours；本模組保持純函式、不依賴 DB。每請求查 DP_USER 狀態之認證閘（T014）另立。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow


@dataclass(frozen=True)
class JwtPayload:
    """已驗證的 Access Token 內容（時間欄位皆為 aware datetime，不可變）。"""

    sub: str
    auth_time: datetime
    iat: datetime
    exp: datetime


def _epoch_to_dt(value: int) -> datetime:
    """epoch 秒 → aware datetime（UTC）。"""
    return datetime.fromtimestamp(value, tz=timezone.utc)


def create_access_token(*, sub: str, ttl_minutes: int, auth_time: datetime | None = None) -> str:
    """簽發 Access Token。

    Args:
        sub: 使用者 USER_ID。
        ttl_minutes: 閒置逾時（分鐘），決定 exp = 簽發時間 + ttl；值取自 DP_PARAM JWT.ACCESS_TTL_MIN。
        auth_time: 本次登入時間；新登入不帶（預設當下），換發時沿用原值以套用單日換發上限。

    Returns:
        簽章後的 JWT 字串。
    """
    now = utcnow()
    at = auth_time or now
    # 防禦：呼叫方誤傳 naive datetime 時，timestamp() 會依系統本地時區誤算 epoch。
    # 依時間處理規範（sti-backend-modules）補為 UTC aware。
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    claims = {
        "sub": sub,
        "auth_time": int(at.timestamp()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> JwtPayload:
    """驗證並解碼 Access Token。

    僅接受設定檔指定的對稱演算法（algorithms 白名單），杜絕 alg=none / 演算法混淆。
    簽章錯誤、過期、格式不符或缺必要 claim 一律拋 AppError（401 / DP_AUTH_002），
    不區分細節以免洩漏資訊。
    """
    try:
        raw = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return JwtPayload(
            sub=raw["sub"],
            auth_time=_epoch_to_dt(raw["auth_time"]),
            iat=_epoch_to_dt(raw["iat"]),
            exp=_epoch_to_dt(raw["exp"]),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        # OverflowError / OSError：fromtimestamp 對離譜（過大 / 負值）epoch claim 會拋，
        # 一併收斂為憑證無效，避免落入通用 500。
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002") from exc


def renew_access_token(token: str, *, ttl_minutes: int, renew_max_hours: int) -> str:
    """活動換發：驗現行 token 仍有效 + 單日換發上限內，沿用 auth_time 重簽。

    Args:
        token: 現行仍有效的 Access Token。
        ttl_minutes: 新 token 的閒置逾時（DP_PARAM JWT.ACCESS_TTL_MIN）。
        renew_max_hours: 自 auth_time 起可換發的上限時數（DP_PARAM JWT.RENEW_MAX_HOURS）。

    Returns:
        沿用原 auth_time、exp 更新的新 JWT。

    Raises:
        AppError: 現行 token 無效 / 過期（DP_AUTH_002）；距 auth_time 已逾換發上限（DP_AUTH_003）。
    """
    payload = decode_access_token(token)
    if utcnow() - payload.auth_time >= timedelta(hours=renew_max_hours):
        raise AppError(status_code=401, detail="已達單次登入時數上限，請重新登入", error_code="DP_AUTH_003")
    return create_access_token(sub=payload.sub, ttl_minutes=ttl_minutes, auth_time=payload.auth_time)
