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
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import AppError
from app.core.password_policy import is_password_expired
from app.core.utils import utcnow

# 認證閘天生綁定平台身分表 DP_USER；此為 core 對平台身分表之唯讀查詢（非跨業務模組耦合）。
from app.dp.users.models import DpUser

#: `PWD_POLICY.EXPIRY_DAYS` 查無 / 無法解析時的後備值；與 `dp/user/service.py` 的登入判定同值。
_DEFAULT_PWD_EXPIRY_DAYS = 90


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
        if raw.get("typ") is not None:
            # 拒絕任何帶 `typ` 的專用票券（目前為 ET 影片播放票，`et/learning/video_ticket`）。
            #
            # 那些票會出現在 URL 與 access log；若能當一般 access token 用，從 log 撈到
            # 一張就等於一組帳號憑證。在此明確擋下，讓「票 ↔ token 不可互換」有**單一
            # 守門人**——先前實際擋住它的是下方 `raw["auth_time"]` 的 KeyError，那是個
            # 間接性質：有人把 auth_time 改成選填（看起來是無害的向後相容改動）就會
            # 靜默打開這條路。
            raise KeyError("typ")
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


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_jwt_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> JwtPayload:
    """所有需認證端點的統一認證閘。

    驗 Bearer token 後，**每請求**查 DP_USER 狀態（research §3：停用 / 鎖定下次請求即拒，
    不做行程內快取）。缺 token / 簽章過期竄改 / 查無 / 已刪 → 401（DP_AUTH_002，不洩帳號
    存在性）；停用 → 403（DP_AUTH_004）；鎖定中 → 403（DP_AUTH_005，LOCKED_UNTIL 逾時視為自動解鎖）。

    Returns:
        通過驗證的 JwtPayload。

    Raises:
        AppError: 認證失敗（401）或帳號狀態不允許（403）。
    """
    if credentials is None:
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")

    payload = decode_access_token(credentials.credentials)
    user = await ensure_user_active(db, payload.sub, payload.auth_time)
    await ensure_password_current(db, user)
    return payload


async def get_jwt_payload_pwd_exempt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> JwtPayload:
    """**逃生門**：認證與帳號狀態照驗，但**不檢查密碼是否須變更**（#929）。

    `get_jwt_payload` 會把「須變更密碼」的帳號一律擋成 403 `DP_AUTH_009`。若連
    「改密碼」本身也被擋，使用者就再也出不來——這支給的就是那組非放行不可的端點。

    ## 白名單（⛔ 逐一列舉，不以路徑前綴比對）

    | 端點 | 非放行不可的理由 |
    |---|---|
    | `PUT /dp/user/me/password` | 改密碼本身；擋了即死鎖（經 `get_operator_pwd_exempt`）|
    | `GET /dp/user/me/password-policy` | 變更表單要顯示「至少 N 字元」 |
    | `POST /dp/user/renew` | 填表期間 token 可能到期，不能換發會打到一半被登出 |
    | `POST /dp/user/logout` | 強制變更頁的「返回登入」會呼叫它（`ForceChangePasswordShell`）|

    ⛔ **判準是「解決問題或離開所需」，不是「方便」**。本清單只有四條，刻意不在此列的有三支：

    - `PUT /dp/user/me`（改姓名）、`PUT /dp/user/me/email`：`spec_us8` FR-DP-US8-08 要求
      「完成變更前 MUST NOT 允許離開至其他功能」，兩者既非解決問題、也非離開所需。
    - `GET /dp/user/me`（讀個資）：⚠️ **它曾以「頂列顯示姓名，擋了畫面壞」的理由進過本清單，
      那個理由是假的**。前端在這個狀態下**刻意不發**這支查詢——`AppHeader.tsx` 與
      `WelcomePage.tsx` 的 me query 都是 `enabled: isAuthenticated && !mustChangePwd`，
      `ForceChangePasswordShell` 自己也從不呼叫它。還會發的只有 `ProfilePage` / `UsersPage`，
      而那兩頁在此狀態下被全畫面頁殼蓋住、使用者看不到也點不到。它又是這組端點中唯一
      回傳 PII（登入 Email、姓名、待驗證新信箱）的一支，故改走預設閘。

    ⛔ **不要改成 `/dp/user/me*` 之類的前綴比對**：前綴會讓日後新增的 `/me/xxx` 端點
    **自動**落入白名單，而沒有任何人決定過它該不該進來——上面那三支正是會被前綴誤收的。

    ⚠️ 豁免的**只有密碼狀態**：停用 / 鎖定 / 已刪 / token 早於密碼變更仍照擋。
    """
    if credentials is None:
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")

    payload = decode_access_token(credentials.credentials)
    await ensure_user_active(db, payload.sub, payload.auth_time)
    return payload


def token_issued_before_password_change(auth_time: datetime, pwd_changed_date: datetime) -> bool:
    """本次登入是否早於最後一次密碼變更（#941）。

    用於讓「密碼變更前簽發的 token」立即失效：帳號被他人登入時，主人改密碼即可踢掉對方。
    比 `auth_time` 而非 `iat`——換發時 `auth_time` 沿用原值（見 `renew_access_token`），
    比它才能讓**同一次登入衍生的所有 token** 一起失效，而不是只失效最後換發的那一張。

    ⚠️ **`pwd_changed_date` 必須取整秒再比**：`auth_time` 由 epoch 整數秒還原
    （`_epoch_to_dt`）、微秒恆為 0，而 `PWD_CHANGED_DATE` 是 `TIMESTAMPTZ`、帶微秒。
    直接比的話，「同一秒內改完密碼又登入」的**新** token（如 08:00:01.000000）會小於
    變更時間（08:00:01.500000）而被判成舊的——使用者剛登入就被登出，且重登一次還是一樣，
    形成登出迴圈。取整秒後兩者相等、不成立。

    ## 這道閘保證到哪裡（⛔ 不要讀成「所有 token 全數立刻失效」）

    **① 與變更落在同一秒的登入**（窗口 < 1 秒）
    floor 使「變更時間所在的那一整秒」內取得的 token 都算有效，包含變更**之後**才簽發的。
    不改用上取整：本功能完成後會把使用者送回登入頁，上取整會讓他當下那次重登被彈回一次。

    > 📌 `pwd_changed_date` **取在寫入前**（`profile_service` / `forgot_service` 的
    > `pwd_changed_at`），不是 service 開頭的 `now`。沿用開頭的值會把窗口拉長到
    > verify + 三次 DB 往返 + `is_reused`（`HISTORY_COUNT` 上限 24 ⇒ 最長約 4.4 秒）。
    > ⛔ 不要為了「與稽核時間一致」把它改回 `now`——那不是一致性問題，是失效基準的正確性。

    **② 已簽發的影片播放票**（窗口最長 5 分鐘）
    票為獨立簽發、取檔時不查 DB（`et/learning/video_ticket.py`）。該檔已載明同一窗口
    適用於「發票後帳號被停用」，密碼變更是同一個形狀，非本機制新增的缺口。

    兩者都是**已知且已接受**的，寫在這裡是因為「密碼一改，所有 token 立刻失效」這句話
    太容易被當成無條件成立，日後有人據此推導出錯的結論。
    """
    return auth_time < pwd_changed_date.replace(microsecond=0)


async def must_change_password(db: AsyncSession, user: DpUser, *, now: datetime | None = None) -> bool:
    """使用者是否處於「須變更密碼」狀態——**登入端點與每請求閘共用的唯一判定**。

    `MUST_CHANGE_PWD` 為真，或 `PWD_CHANGED_DATE` 逾 `PWD_POLICY.EXPIRY_DAYS`。

    ⛔ **不要在呼叫端另寫一份**：登入（`dp/user/service.py::login`）據此決定回應的
    `must_change_pwd`、本閘據此擋下請求。兩邊若各寫一次，一旦漂移就會出現「登入說要改、
    閘說不用改」（使用者看到強制變更頁卻其實沒被擋）或反向的「登入說不用改、閘卻一直擋」
    （改完密碼仍進不去）。後備值與參數解析一併收在這裡，避免兩份 90。

    `now` 供登入端傳入該請求的統一時點；閘門不傳，取當下即可。

    ## `EXPIRY_DAYS` 取不到或取到怪值時的行為（**刻意的，不是遺漏**）

    | 參數狀態 | `get_int_param` 回傳 | 本函式 |
    |---|---|---|
    | 查無列 / 已軟刪 / `IS_ENABLED=false` / 值非整數 | 90（後備值）| **fail-closed**，照擋 |
    | 值 ≤ 0 | 原值 | **fail-open**：效期判定整個關閉（`is_password_expired` 明載 ≤ 0 為停用效期）|

    ⚠️ 走 API 設不到 ≤ 0（`param_rules.py` 的 `IntRule(1, 90)`），唯一路徑是直接改 DB。
    ⛔ **不要在這裡夾回**：`is_password_expired` 把「≤ 0 ＝停用效期」寫成了支援的語意，
    在呼叫端悄悄推翻它，會變成「文件說可以關、實際關不掉」。要改就改那一側。

    🔴 但要知道這條的份量**在 #929 之後變了**。`MUST_CHANGE_PWD` 不由任何應用程式路徑設為
    true（`repository.create_user` 的該參數目前無呼叫端會傳 True），只由兩支 migration 設：
    `36af0d3943bf`（`edmsops`，無條件）與 `4c6a9a8595a4`（`DEMOADMIN` 等示範帳號，**僅當
    密碼仍為 seed 雜湊**）。也就是說**一般使用者恆為 false，這道閘對他們只由效期驅動**——
    把 `EXPIRY_DAYS` 設成 0 對那群人不是關掉其中一條判定，是關掉整道閘。
    """
    # 延遲載入避免 core → app.services 匯入循環（app.services 匯入的 dp 服務會回頭依賴 core）
    from app.services import ParamService

    if user.must_change_pwd:
        return True
    expiry_days = await ParamService().get_int_param(db, "PWD_POLICY", "EXPIRY_DAYS", _DEFAULT_PWD_EXPIRY_DAYS)
    return is_password_expired(user.pwd_changed_date, expiry_days, now=now)


async def ensure_password_current(db: AsyncSession, user: DpUser) -> None:
    """密碼須為現行有效，否則 403 `DP_AUTH_009`（#929）。

    ## 為什麼收 `user` 而不是 `user_id`

    呼叫端（`get_jwt_payload`）剛剛才經 `ensure_user_active` 把整個 `DpUser` 查出來。
    收已載入的實體可**沿用那一次查詢**；本閘的額外成本只剩 `EXPIRY_DAYS` 這一次參數查詢。
    舊版 `password_gate.require_password_current` 是自己再查一次 `DpUser`，掛到全站等於
    每請求多兩次查詢。

    ⚠️ `ParamService` 目前**無快取**（每次打 DB）。單鍵查詢與既有的 `DpUser` 查詢同級，
    故接受；若日後成為瓶頸再評估加參數快取——⛔ 不要順手加，新增快取＝新增失效窗。
    """
    if await must_change_password(db, user):
        raise AppError(status_code=403, detail="請先變更密碼後再繼續", error_code="DP_AUTH_009")


async def ensure_user_active(db: AsyncSession, user_id: str, auth_time: datetime) -> DpUser:
    """帳號存在、未停用、未鎖定、token 不早於密碼變更；`get_jwt_payload` 每請求都查。

    `auth_time` 為**必填**（不給預設值）：耗時長的請求會在寫入前再查一次
    （見 `et/material/service.py::_reauthorize`），漏傳即型別檢查失敗，不會靜默少一道檢核。

    ⚠️ 查的是整個 `DpUser` 實體：同一個 session 先前已載入、且仍有人持有該實體時，重查只會拿回
    記憶體裡的舊值（`expire_on_commit=False`）。請求中途再查前，呼叫端要先 `db.expire_all()`。

    Returns:
        通過檢查的 `DpUser`——供呼叫端接著做密碼狀態判定（`ensure_password_current`）而
        **不必再查一次**。現有的兩個呼叫端忽略回傳值即可。

    Raises:
        AppError: 查無 / 已刪 / token 早於密碼變更（401 `DP_AUTH_002`）、停用（403 `DP_AUTH_004`）、
            鎖定中（403 `DP_AUTH_005`）。
    """
    result = await db.execute(select(DpUser).where(DpUser.user_id == user_id, DpUser.deleted == 0))
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")
    if user.status != "ACTIVE":
        raise AppError(status_code=403, detail="帳號已停用", error_code="DP_AUTH_004")
    if user.locked_until is not None and user.locked_until > utcnow():
        raise AppError(status_code=403, detail="帳號已鎖定", error_code="DP_AUTH_005")
    # 與其他無效 token 回同一個 401 / DP_AUTH_002：不另設錯誤碼，免得替「拿著舊 token 的那一方」
    # 指出「密碼剛被改過」——那一方可能正是盜用者（#941）。
    if token_issued_before_password_change(auth_time, user.pwd_changed_date):
        raise AppError(status_code=401, detail="登入憑證無效或已逾時，請重新登入", error_code="DP_AUTH_002")
    return user
