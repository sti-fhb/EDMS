"""強制變更密碼閘（T023）。

登入回 must_change_pwd=true 時前端進強制變更頁；此閘確保後端同步把關——凡套用本閘的
需認證端點，若 token 使用者處於「須變更密碼」狀態（MUST_CHANGE_PWD=true 或 PWD_CHANGED_DATE
逾效期），一律 403 DP_AUTH_009，前端據此導向強制變更頁。變更密碼提交端點屬 US8，不套用本閘；
換發 / 登出亦不套用（須變更者仍需能換發、登出）。
"""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.password_policy import is_password_expired
from app.dp.users.models import DpUser

_DEFAULT_EXPIRY_DAYS = 90


async def require_password_current(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> JwtPayload:
    """需認證且密碼為現行有效狀態的閘。

    先經 get_jwt_payload 完成認證（含 DP_USER 狀態檢查），再檢核密碼狀態：
    MUST_CHANGE_PWD=true 或 PWD_CHANGED_DATE 逾效期 → 403 DP_AUTH_009。

    Returns:
        通過（密碼現行有效）的 JwtPayload。

    Raises:
        AppError: 須變更密碼（403 DP_AUTH_009）；認證失敗由 get_jwt_payload 拋（401 / 403）。
    """
    # 延遲載入避免 core → app.services 匯入循環（app.services 匯入的 dp 服務會回頭依賴 core）
    from app.services import ParamService

    result = await db.execute(select(DpUser).where(DpUser.user_id == payload.sub, DpUser.deleted == 0))
    user = result.scalar_one_or_none()
    if user is None:
        # 理論上 get_jwt_payload 已擋，防禦性再判一次
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")

    must_change = user.must_change_pwd
    if not must_change:
        raw = await ParamService().get_param_value(db, "PWD_POLICY", "EXPIRY_DAYS")
        try:
            expiry_days = int(raw) if raw is not None else _DEFAULT_EXPIRY_DAYS
        except ValueError:
            expiry_days = _DEFAULT_EXPIRY_DAYS
        must_change = is_password_expired(user.pwd_changed_date, expiry_days)

    if must_change:
        raise AppError(status_code=403, detail="請先變更密碼後再繼續", error_code="DP_AUTH_009")
    return payload
