"""認證端點（US1 / US2 / US3）：登入 / 註冊 / 忘記密碼 / 重設密碼（匿名）/ 換發 / 登出 / 入口頁模組摘要。"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.cooldown import VerifySendCooldown
from app.core.db import get_db
from app.core.log_redaction import mask_email
from app.core.module_admin import module_admin_gate
from app.core.module_roles import module_role_gate
from app.core.operator import OperatorInfo, get_operator
from app.core.password_gate import require_password_current
from app.core.rate_limit import (
    LOGIN_RATE_MAX,
    RATE_WINDOW_SECONDS,
    REGISTER_RATE_MAX,
    SET_PASSWORD_RATE_MAX,
    SlidingWindowCounter,
    SlidingWindowRateLimiter,
    rate_limit_by_ip,
)
from app.core.request_context import get_client_ip
from app.dp.user.activate_service import ActivateAccountService
from app.dp.user.email_change_service import EmailChangeService
from app.dp.user.forgot_service import ForgotPasswordService, ResetPasswordService
from app.dp.user.profile_service import ProfileService
from app.dp.user.register_service import RegisterService, email_unavailable_error
from app.dp.user.schemas import (
    ActivateAccountRequest,
    ApplicablePasswordPolicyResponse,
    EmailChangeRequest,
    EmailChangeVerify,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ModuleRoleStatus,
    ModuleSummary,
    NameUpdate,
    PasswordChange,
    PasswordPolicyResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordPolicyRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.dp.user.service import AuthService
from app.dp.user.verify_service import ResendVerificationService, VerifyService
from app.services import ParamService

# 登入限流器（行程內；IP 與帳號維度共用同一器、以 key 前綴區分）
_login_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊限流器（IP + 帳號雙維度共用此實例）。門檻與登入解耦、且刻意較登入寬鬆——
# 自助註冊為主要入口，須容納「同一出口 IP 多人同時註冊」的正常尖峰；同一 Email 的
# 重複註冊由下方 600 秒寄信冷卻把關，不靠本門檻（理由詳見 core/rate_limit.py 的 #44 段）
_register_limiter = SlidingWindowRateLimiter(max_requests=REGISTER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 忘記密碼申請 / 重設限流器（IP + 帳號維度；防列舉與暴力）
_forgot_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_reset_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 註冊驗證端點限流器（IP 維度）；重寄另加帳號維度防濫發
_verify_limiter = SlidingWindowRateLimiter(max_requests=SET_PASSWORD_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_resend_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 帳號啟用端點限流器（IP 維度；受邀者持 token 設密碼）
_activate_limiter = SlidingWindowRateLimiter(max_requests=SET_PASSWORD_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# 密碼變更 / Email 變更申請限流器（IP + 帳號維度；US8 FR-07 防高頻嘗試）
_pwd_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_email_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# Email 變更驗證端點限流器（IP 維度；公開落點）
_verify_email_change_limiter = SlidingWindowRateLimiter(max_requests=LOGIN_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
# Email 變更寄信冷卻（比照註冊 #74）：同帳號兩次寄驗證信間隔至少 VERIFY_SEND_COOLDOWN_SEC（預設 10 分）
_email_change_cooldown = VerifySendCooldown()
# 驗證信寄送冷卻（#74）：register 與 resend 共用同一器、同一 Email key，
# 600 秒內對同一 Email 只放行一封（堵「以重新註冊繞過重寄冷卻」）
_verify_send_cooldown = VerifySendCooldown()
_params = ParamService()
_VERIFY_SEND_COOLDOWN_DEFAULT = 600


# 同一 Email 每日重建待驗證列的次數上限（#234）。window 固定 24 小時，**上限值於請求時**
# 自 DP_PARAM 讀取，故用 SlidingWindowCounter（不在建構時固定上限、達上限不拋）而非 limiter。
_OVERWRITE_WINDOW_SECONDS = 86_400
_OVERWRITE_MAX_DEFAULT = 5
# 讀取端的值域收斂。**不放 `param_rules.py` 的 IntRule**：該參數為 `EDIT_SCOPE='HIDDEN'`，
# 而 `is_editable_scope` 的 403 擋在值域檢核**之前** —— IntRule 對它永遠走不到，等於為不存在
# 的 code path 寫防禦（違反 sti-coding-style）。真正走得到的路徑是「IT 直接改 DB」，
# 而 `get_int_param` 對整數不設界：設成 99999 會靜默關掉這道防護，故在此收斂。
_OVERWRITE_MAX_RANGE = (1, 10)
_overwrite_counter = SlidingWindowCounter(window_seconds=_OVERWRITE_WINDOW_SECONDS)


def _overwrite_key(email: str) -> str:
    """每日重建額度的分桶鍵：**Email 維度**。

    ⚠️ 不加 IP 維度：加了就是換 IP 即繞過。代價是它分不出攻擊者與受害者——
    攻擊者用罄額度後，受害者本人也寄不出信（#234 AC 2 只能部分達成，詳見該 issue 規劃留言）。
    """
    return f"register-overwrite:{email.lower()}"


async def _overwrite_max(db: AsyncSession) -> int:
    """每日上限值，收斂至 `_OVERWRITE_MAX_RANGE`；超界留 log 後夾回。

    ⚠️ 占用時間是 **本值 × RESET_TOKEN_TTL_MIN**，兩者互鎖。只收斂本值不足以界定占用：
    上限 10 搭配 TTL 120 分鐘即為 20 小時／日，本修法形同失效。調整任一者時請一併評估另一者。
    """
    raw = await _params.get_int_param(db, "LOGIN", "REGISTER_OVERWRITE_MAX_PER_DAY", _OVERWRITE_MAX_DEFAULT)
    low, high = _OVERWRITE_MAX_RANGE
    if raw < low or raw > high:
        # 扣下動作必留痕：靜默夾回會讓「我明明設了 99999」與「防護沒生效」對不起來。
        logger.warning("每日重建上限 %s 超出 %s，已夾回", raw, _OVERWRITE_MAX_RANGE)
    return max(low, min(high, raw))


def _verify_send_key(email: str) -> str:
    """驗證信寄送冷卻分桶鍵（register / resend 共用同一 Email 額度）。**只在真的寄出信時蓋章。**"""
    return f"verify-send:acct:{email}"


def _verify_send_probe_key(email: str) -> str:
    """「未寄出」時改蓋的分桶鍵：只對發起者自己生效（#213 候選 2）。

    原本 resend 是**無條件**蓋 Email 章（為防列舉：讓 429 的有無不因該 Email 是否有待驗證列而異）。
    但 resend 對「Email 不存在 / 是 ADMIN_INVITE / 已逾期」是靜默不寄，於是任何匿名者打一次
    resend 就能替任意 Email 蓋 600 秒章，而該 key 與 register 共用 → 受害者註冊得到 429，
    每 10 分鐘重打一次即可**無限期封鎖**，且無稽核、無寄信紀錄、狀態只在行程記憶體
    （「重啟服務好一下、幾分鐘又壞」會把排查方向整個帶錯）。

    改為「冷卻由**信**來武裝」：真的寄出才蓋 Email 章（防狂發語意不變），沒寄信只蓋本 key，
    使發起者自己重打仍得到形狀完全相同的 429、但不波及他人。

    key 必須帶 email 而非只帶 IP：辦公室 / 教室 NAT 下，一個人探測會擋掉同事對**自己** Email
    的重寄。IP 缺失（無法解析 client）時退 "unknown" 分桶——該情境下所有請求共用一桶，
    退化為與改動前相近的行為，不會比原本更寬鬆。

    已知取捨（記於 #213 決策留言）：key 基數由 |email| 變為 |email| + |ip×email|。攻擊者付的成本
    其實**沒有變**——改動前每次 resend 也蓋一個 acct key，同 IP 對同 email 重打第二次起就 429、
    不再產生新 key，所以要灌 key 一樣得換 email、每請求 1 個 key。基數膨脹只發生在正常的 NAT
    多人使用上，那是有界的。

    `VerifySendCooldown` 達 `_max_keys` 上限時為 **fail-open**（不擋，交 IP 限流兜底）；穩態 key 數
    約為「到達率 × `_MAX_RETENTION_SEC`」，故單一 IP **永遠到不了**上限（10 次/分 × 1 小時保留
    ≈ 600 個 key）。實際門檻與後果見 `core/cooldown.py` 之 `_MAX_RETENTION_SEC` 註解（該處已依
    review 由 1 天下調為 1 小時）。
    """
    return f"verify-send:probe:{get_client_ip() or 'unknown'}:{email}"


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])
_service = AuthService()
_register_service = RegisterService()
_verify_service = VerifyService()
_resend_service = ResendVerificationService()
_forgot_service = ForgotPasswordService()
_reset_service = ResetPasswordService()
_activate_service = ActivateAccountService()
_profile_service = ProfileService()
_email_change_service = EmailChangeService()

_DEFAULT_MIN_LEN = 8
_DEFAULT_ADMIN_MIN_LEN = 12
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_HISTORY_COUNT = 3
_DEFAULT_EXPIRY_DAYS = 90

# ⚠️ 這三句裡的「30 分鐘」是**寫死的字面值**，而連結的實際效期讀自
# `DP_PARAM.LOGIN.RESET_TOKEN_TTL_MIN`（`EDIT_SCOPE='ADMIN'`，管理者改得動；
# 落地於 `forgot_service.py` / `register_service.py` / `verify_service.py`）。
# **改那個參數時要一併改這三句**，否則畫面會告訴使用者一個錯的期限——調短尤其糟：
# 使用者以為還有時間，點開卻是「連結已失效」。
#
# 前端另有兩份同樣寫死的副本（`auth/ForgotPasswordForm.tsx:11`、`auth/RegisterForm.tsx:87`），
# 且前端顯示的是它自己的常數、不是這裡回的 message。
#
# 所以正式碼要改的是 **3 個檔、共 5 句**：本檔三句 + 前端兩句。
# 另有 4 處測試夾具寫死同一字串（`test/server.ts` ×3、`auth/LoginOverlay.test.tsx` ×1），
# 那些**會自己變紅**，不必事先找——照著紅的改即可，它們反而是「你還沒改完」的提醒。
#
# 核對用（刻意不用 `30 分鐘` 當樣式：那會連 ET 排程 docstring 裡無關的用語一起撈進來，
# 14 筆裡只有 5 筆是真的，雜訊反而讓人以為漏改）：
#     git grep -n "請於 30 分鐘內" -- backend/app frontend/src
#
# 應為 10 筆：5 正式 + 4 測試 + **本行指令自己**（樣式字串就寫在本註解裡，會把自己撈進來）。
#
# 未改成動態插值是刻意的取捨（2026-10-05 橫向檢查）：該參數是安全衛生旋鈕、實務上幾乎不會
# 被調整，而後果僅是使用者多申請一次連結。若日後真的要調整效期（如資安稽核要求縮短），
# 正確作法是讓這三句用讀到的 `ttl_min` 組出來，並讓前端改用後端回的 message。
_FORGOT_MESSAGE = "若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"
_REGISTER_MESSAGE = "驗證信已寄至您的信箱，請於 30 分鐘內點連結設定密碼以完成註冊"
_RESEND_MESSAGE = "若該 Email 有待驗證的註冊，驗證信將重新寄出，請於 30 分鐘內完成驗證"


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_login_limiter, "login")),
) -> LoginResponse:
    """帳密登入（匿名端點）。IP + 帳號雙維度限流；帳號維度**先 hit 限流、後查存在性**防列舉。"""
    _login_limiter.hit(f"login:acct:{data.email}")
    return await _service.login(db, email=data.email, password=data.password)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_register_limiter, "register")),
) -> dict[str, object]:
    """自助註冊（匿名端點，IP 限流防批量灌帳號）。

    方案 B（#56）：檢核 → 寫待驗證表 + 寄驗證信（**不建 DP_USER**），回 202（已受理、待驗證）。
    使用者點信中連結經 /verify-email 通過後才建帳號並啟用。

    帳號維度限流（先 hit、後查）：防輪換 IP 對單一 Email 反覆觸發驗證信（email-bombing），
    與 forgot / resend 一致。

    驗證信寄送冷卻（#74）：check 於檢核前（防列舉）、record 於送信成功後——註冊檢核失敗
    （422/409）不 record，不誤觸冷卻；與 resend 共用同一 Email 額度，堵住繞道重發。

    例外（#86）：**已驗證帳號**的存在性檢核置於冷卻之前。防列舉在此無實益——register 本來
    就以 409「已被註冊」對外洩露已驗證 Email 的存在（冷卻窗外即可分辨），冷卻期擋著只是讓
    使用者白等倒數。pending / 全新 Email 維持冷卻優先，防狂發語意不變。

    ## 回應收斂（#345 / #346）與**未關閉的時間側通道**

    回應只有三種：409（已驗證帳號）、429（**自己的** probe 冷卻）、202（其餘一切）。
    未逾期 `ADMIN_INVITE` 與「他人蓋的 Email 章」都走靜默 202——不寄信、不覆蓋、不換 token、
    不延長效期、不蓋 Email 章。於是 409 恰好等於「`DP_USER` 列存在」，與 login 的
    `DP_AUTH_004/005/008` 同一集合，交叉比對不再產生新資訊。

    ⚠️ **但內容收斂不等於完全不可區分——時間維度仍可區分，本次刻意未處理。**
    靜默路徑只做 2 次查詢 + 蓋章就回；真實路徑還要再跑一次 `assert_email_available`
    （2 次查詢）、刪舊列、插新列、渲染並寫 outbox。攻擊者量得出這個差。

    `assert_email_available` 的 docstring 寫「round-trip 次數是**最後一道**可觀測差異」——
    那句話在該方法**內部**仍成立（兩個分支都跑兩次查詢），但就**整個端點**而言已不再是
    最後一道：差異從 status 退到了時間，不是消失。

    ⚠️ **這個差距是「單一請求即可量測」，不是「要取夠樣本」。** 本機實測（同行程、同 DB、
    且當時 CPU 正被別的測試佔用，屬不利條件）：靜默 202 中位數 9.2 ms、寄信 202 中位數
    17.6 ms，**兩個區間完全不重疊**（11.2 < 16.5）。我原本寫「統計上取夠樣本並不便宜」
    是錯的——理由寫錯比沒寫更危險，下一個人會據此放寬別的東西。

    結構性原因（不是調校得掉的常數）：靜默路徑 3 次 SELECT 後即回；真實路徑另有
    `register()` 內**重複的**可用性查詢、TTL 參數查詢、`DELETE`、`INSERT`、範本查詢、
    outbox `INSERT`，以及有舊 pending 列時的稽核寫入（含交易級 advisory lock）。

    不處理的理由改為：要真的關掉只能對整個端點設固定下限延遲（如一律 ≥120 ms），那會讓
    所有使用者變慢且數值難校準；本次**接受此殘留**。⛔ **不要把這份 docstring 或
    `error-codes.md` 讀成「列舉面完全關閉」**——那正是 #208 的 Security Review 抓到的
    那種過度宣稱，而我在本次已經犯了一次（宣稱 register x resend 也關了，實測並沒有）。
    """
    _register_limiter.hit(f"register:acct:{data.email}")

    # 可用性判定與「回什麼」分離（#345）。兩次查詢一律都跑，見 email_availability 的 docstring。
    registered, invited, _ = await _register_service.email_availability(db, data.email)

    # 已驗證帳號優先於冷卻回應（#86）：那是**終局狀態**，等倒數結束也不會變，且不送信、
    # 冷卻無防狂發價值——先擋可免使用者白等一輪。它維持 409，與 login 的 DP_AUTH_004/005/008
    # 同一集合，所以交叉比對不產生新資訊（#345 刻意保留的一格）。
    if registered:
        raise email_unavailable_error()

    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    sent_key = _verify_send_key(data.email)
    probe_key = _verify_send_probe_key(data.email)

    # **自己的**冷卻才明說（#346）。probe key 是 IP x Email，只有發起者自己蓋得到，
    # 故 429 不洩漏任何關於該 Email 的事實——全新 Email 在同一情境同樣回 429。
    _verify_send_cooldown.check(probe_key, cooldown_sec)

    # **他人**蓋的 Email 章必須靜默（#346）：那把章只在「真的寄出」時蓋（#213），所以
    # 回 429 等於宣告「600 秒內有人對此 Email 成功寄出驗證信」＝有未逾期的自助註冊待驗證列。
    others_cooling = _verify_send_cooldown.remaining(sent_key, cooldown_sec) > 0

    # 每日重建額度（#234）：冷卻只有 600 秒 < TTL 1800 秒，匿名者每 601 秒送一次即可讓該列
    # **永遠不逾期**，於是管理者代建恆 409、SCHDP001 也清不到。額度用罄後停止刷新效期，
    # 該列終會逾期。`count` 無副作用——真的寄出才 `try_record`（同 Email 章的處理）。
    over_cap = _overwrite_counter.count(_overwrite_key(data.email)) >= await _overwrite_max(db)

    if invited or others_cooling or over_cap:
        # 靜默成功：回應與全新 Email 逐欄位相同，且**什麼都不寫**——不寄信、不覆蓋 pending
        # 列、不換 token、不延長效期、不蓋 Email 章。
        #
        # ⚠️ 蓋 Email 章會變成 #213 的封鎖手段（任何匿名者替任意 Email 蓋 600 秒章）；
        # ⚠️ 覆蓋 pending 列會重開 #212（每 600 秒作廢一次受害者的驗證連結）。
        #
        # 唯一允許的寫入是 probe 章，它讓「同一 IP 連打」的回應與全新 Email 對齊（否則
        # 受邀 -> 202,202 而全新 -> 202,429，兩次請求就切得開）。
        _verify_send_cooldown.record(probe_key)
        # 靜默路徑原本**一行 log 都沒有**（Security MEDIUM-2）：批量探測受邀名單時，命中的
        # 那些（真正敏感的那半）在伺服器端完全不可見；客服也分不出「靜默擋下」與「信寄了
        # 沒到」。log 不對外，記它不削弱防列舉。Email 比照既有寫法遮罩。
        logger.info(
            "自助註冊靜默受理 ip=%s email=%s reason=%s",
            get_client_ip(),
            mask_email(data.email),
            "invited" if invited else ("others_cooling" if others_cooling else "over_cap"),
        )
        return {"message": _REGISTER_MESSAGE, "retry_after": cooldown_sec}

    sent = await _register_service.register(
        db,
        email=data.email,
        user_name=data.user_name,
    )
    # 只在真的排入 outbox 才蓋章（冷卻由「信」武裝，同 resend 的處理）：send_email 對範本停用 /
    # channel 非 EMAIL / 渲染失敗是正常回傳 0、不拋例外，那些情況下蓋章會把使用者鎖 600 秒卻連
    # 一封信都沒收到。register 不需要 probe 章——它沒有「靜默不寄」的防列舉需求（已驗證帳號直接
    # 回 409），且此路徑必然已寫入待驗證列，本身就受帳號維度限流約束。
    if sent:
        # Email 章**只在真的寄出時蓋**（#213）：它跨 IP，誤蓋等於讓人封鎖他人 600 秒。
        _verify_send_cooldown.record(sent_key)
        # 每日額度同理由只記真的寄出的那次：它界定的是「對這個信箱實際重建了幾次列」，
        # 靜默路徑既沒建列也沒寄信，記了會讓受害者的額度被探測行為吃掉。
        _overwrite_counter.try_record(_overwrite_key(data.email))
    # probe 章**無條件蓋**（#346）。兩個理由：
    # 1. 只蓋 Email 章的話，同一人重打會撞上它而落入**靜默** 202——他以為信一直在寄、
    #    實際一封都沒有，防狂發在改制後會從 429 退化成無聲。
    # 2. ⚠️ 若只在 `sent` 時蓋，範本被停用（`send_email` 回 queued_count=0）時全新 Email
    #    兩個章都沒蓋 → 同 IP 第二次回 202；而受邀者走靜默路徑一律蓋 probe → 429。
    #    **那會讓「範本誤設」變成一個新的列舉面。** 無條件蓋即與靜默路徑對齊。
    # probe 是 IP x Email、只影響發起者自己，無條件蓋不會波及他人（與 Email 章的性質不同）。
    _verify_send_cooldown.record(probe_key)
    return {"message": _REGISTER_MESSAGE, "retry_after": cooldown_sec}


@router.post("/verify-email")
async def verify_email(
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_verify_limiter, "verify")),
) -> dict[str, str]:
    """驗證註冊 token（匿名，持信中連結 token）→ 建 DP_USER + 授 ET 學員 + 雙稽核 + 刪待驗證列。"""
    await _verify_service.verify(
        db, token=data.token, new_password=data.new_password, confirm_password=data.confirm_password
    )
    return {"message": "帳號已啟用，請以新密碼登入"}


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_resend_limiter, "resend")),
) -> dict[str, object]:
    """重寄註冊驗證信（匿名）。一律回相同訊息（防列舉）；僅對待驗證帳號作廢舊 token、產新並重寄。

    帳號維度**先 hit 限流、後查存在性**（同 forgot，防以 429 反推）。

    驗證信寄送冷卻（#74 + #213）：**兩個維度都 check**（皆於查存在性前，故 429 的有無不因該
    Email 是否有待驗證列而異——防列舉），但**只有真的寄出信才蓋 Email 章**：

    - 有寄出 → 蓋 `_verify_send_key`（Email 維度，與 register 共用額度、防對同一信箱狂發）
    - 沒寄出 → 只蓋 `_verify_send_probe_key`（IP×Email 維度，只影響發起者自己）

    改動理由見 `_verify_send_probe_key` 的 docstring（#213）：原本無條件蓋 Email 章，使任何匿名者
    打一次 resend 就能無限期封鎖任意 Email 的自助註冊。

    ⚠️ **#345 起 `check` 也分兩層**：只有**自己的** probe 章回 429；**他人**蓋的 Email 章改為
    靜默（不寄、回 200）。原本無條件 `check(sent_key)` 讓「有沒有 acct 章」可跨 IP 讀出，
    而那等同於「register 剛才是真寄還是靜默」＝「這個 Email 是不是受邀者」——兩個請求即可
    決定性取出邀請名單。詳見下方實作處的註解。

    成功回應帶 retry_after（＝完整冷卻秒數）供前端起算倒數；兩條路徑的回應完全相同。
    """
    _resend_limiter.hit(f"resend:acct:{data.email}")
    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    sent_key = _verify_send_key(data.email)
    probe_key = _verify_send_probe_key(data.email)

    # **自己的**冷卻才明說（#345 Security HIGH-1，與 register 同一設計）
    _verify_send_cooldown.check(probe_key, cooldown_sec)

    # ⚠️ **他人蓋的 Email 章必須靜默，不得回 429。** 這一段是 #345 關閉列舉面的另一半：
    #
    # acct 章只在「真的寄出」時蓋（#213），而 register 對未逾期邀請是靜默不寄、不蓋章。
    # 於是「有沒有 acct 章」＝「register 剛才是真寄還是靜默」＝「這個 Email 是不是受邀者」。
    # 本端點原本無條件 `check(sent_key)`，等於把那個事實跨 IP 讀出來：
    #
    #   ① register {V} 自 IP1 -> 一律 202（看不出東西）
    #   ② resend   {V} 自 IP2 -> 429 ⇒ ① 真的寄了 ⇒ V 不是受邀者
    #                            200 ⇒ ① 是靜默的 ⇒ V 是未逾期 ADMIN_INVITE
    #
    # 兩個請求、決定性，且**命中時完全無聲**（兩步都不寄信），與 #345 原本要修的殘留同級。
    #
    # ⛔ **防轟炸的目的不變、只換手段**：`test_real_resend_still_cooled_across_ips` 的
    # docstring 寫「key 加 IP 維度會讓換 IP 就能對同一信箱無限發信」——那道保護由「仍然
    # 不寄」承接（下方 early return 不呼叫 resend），改掉的只是「要不要用 429 昭告」。
    # 該測試因此改為斷言「200 且 outbox 未新增」，性質沒放棄，只是改用副作用驗。
    # 🔴 每日重建額度與 register **共用同一份**（#234）。`verify_service.resend` 與
    # `register_service.register` 同形——都是 `delete_pending_unless_active_invite` +
    # `create_pending_registration(expires_date=now + ttl)`，**重寄一樣會刷新效期**。
    # 只擋 register 的話，攻擊者改打本端點即完全繞過，修法等於沒做。
    # 既有的 600 秒冷卻早已為同一理由共用額度（`FR-DP-US2-04b`：「避免以重新註冊繞過重寄冷卻」）。
    over_cap = _overwrite_counter.count(_overwrite_key(data.email)) >= await _overwrite_max(db)

    if over_cap or _verify_send_cooldown.remaining(sent_key, cooldown_sec) > 0:
        _verify_send_cooldown.record(probe_key)
        return {"message": _RESEND_MESSAGE, "retry_after": cooldown_sec}

    sent = await _resend_service.resend(db, email=data.email)
    if sent:
        _verify_send_cooldown.record(sent_key)
        _overwrite_counter.try_record(_overwrite_key(data.email))
    # probe 章無條件蓋（同 register）：否則「有沒有被蓋 probe」又會隨 sent 而異。
    _verify_send_cooldown.record(probe_key)
    return {"message": _RESEND_MESSAGE, "retry_after": cooldown_sec}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_forgot_limiter, "forgot")),
) -> dict[str, str]:
    """忘記密碼申請（匿名）。一律回相同訊息（防列舉）；帳號存在才產 token 並寄信。

    帳號維度**先 hit 限流、後查存在性**（同登入，防以 429 反推帳號）。
    """
    _forgot_limiter.hit(f"forgot:acct:{data.email}")
    await _forgot_service.request(db, email=data.email)
    return {"message": _FORGOT_MESSAGE}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_reset_limiter, "reset")),
) -> dict[str, str]:
    """以 token 重設密碼（匿名，持信中連結 token）。驗 token + 複雜度 + 重複性 → 更新 + 作廢 + 稽核。"""
    await _reset_service.reset(
        db, token=data.token, new_password=data.new_password, confirm_password=data.confirm_password
    )
    return {"message": "密碼已更新，請以新密碼登入"}


@router.post("/reset-password/policy", response_model=ApplicablePasswordPolicyResponse)
async def reset_password_policy(
    data: ResetPasswordPolicyRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_reset_limiter, "reset-policy")),
) -> ApplicablePasswordPolicyResponse:
    """重設頁適用之密碼門檻（匿名，持信中連結 token，#623）：管理者 12、其餘 8。

    token 無效回一般門檻、不報錯；連結失效仍由送出時的 `/reset-password` 告知。
    """
    rules = await _reset_service.password_rules_for_token(db, token=data.token)
    return ApplicablePasswordPolicyResponse(min_len=rules.min_len, char_types=rules.char_types)


@router.post("/activate-account")
async def activate_account(
    data: ActivateAccountRequest,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_activate_limiter, "activate")),
) -> dict[str, str]:
    """帳號啟用（匿名，持邀請信連結 token，US4 #67）。

    受邀者自設密碼 → 驗 token（僅 ADMIN_INVITE）+ 效期 + 複雜度 → 建 DP_USER(ACTIVE) + 授 ET 學員
    + 雙稽核 + 首筆 PWD_HIST + 刪待邀請列（重用 activate_pending_account）。
    """
    await _activate_service.activate(
        db, token=data.token, new_password=data.new_password, confirm_password=data.confirm_password
    )
    return {"message": "帳號已啟用，請以新密碼登入"}


@router.post("/dp/user/renew", response_model=TokenResponse)
async def renew(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """活動換發：需現行有效 token。get_jwt_payload 先過 DP_USER 狀態閘，再驗單日換發上限重簽。"""
    return await _service.renew(db, payload=payload)


@router.post("/dp/user/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> None:
    """登出：需認證。寫 LOGOUT 稽核後回 204（無狀態 JWT，前端自行丟棄 token）。"""
    await _service.logout(db, user_id=payload.sub)


@router.get("/dp/user/module-summary", response_model=ModuleSummary)
async def module_summary(
    payload: JwtPayload = Depends(require_password_current),
    db: AsyncSession = Depends(get_db),
) -> ModuleSummary:
    """入口頁 / 側欄模組摘要：需認證且密碼現行有效（強制變更者擋於閘）。

    ET / DM 皆經 `has_any_role` 判定閘聚合（contracts §4）；未註冊模組 fail-closed
    回 False＝未開通。

    > **ET 原為寫死 `True`**（理由：學員為預設角色、人人皆有），因當時 ET 尚未註冊
    > checker、問閘必得 False，側欄會永遠不顯示「教育訓練」。#185 接線後該權宜前提
    > 消失，且變成錯誤來源——管理者於 DP 後台**取消**某人之學員角色後（#185 開通此
    > 能力），側欄仍會顯示 ET 群組，但其所有 ET 端點都會被存取閘以 403
    > `ET_AUTH_001` 擋下。改為實查使 側欄與存取閘一致。
    """
    et_has_role = await module_role_gate.has_any_role("ET", payload.sub, db)
    dm_has_role = await module_role_gate.has_any_role("DM", payload.sub, db)
    # is_admin（#250）：供側欄決定「系統管理者後台」群組可見性，與 DP 後台端點之
    # require_any_module_admin 同源（module_admin_gate），避免側欄承諾閘不給的東西
    et_is_admin = await module_admin_gate.is_module_admin("ET", payload.sub, db)
    dm_is_admin = await module_admin_gate.is_module_admin("DM", payload.sub, db)
    return ModuleSummary(
        et=ModuleRoleStatus(has_role=et_has_role, is_admin=et_is_admin),
        dm=ModuleRoleStatus(has_role=dm_has_role, is_admin=dm_is_admin),
    )


# --- 個人資料維護（US8 /me；需認證，不套 require_password_current 逃生門） ---


@router.get("/dp/user/me", response_model=MeResponse)
async def get_me(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """本人個人資料：姓名 / 帳號（Email）/ 待驗證新信箱。"""
    user = await _profile_service.get_me(db, user_id=payload.sub)
    return MeResponse.model_validate(user)


@router.get("/dp/user/me/password-policy", response_model=ApplicablePasswordPolicyResponse)
async def get_my_password_policy(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
) -> ApplicablePasswordPolicyResponse:
    """本人設定新密碼時適用之門檻（#623）：管理者 12、其餘 8。

    ⚠️ 刻意用 `get_jwt_payload` 而非 `require_password_current`：密碼逾期者被導到強制變更密碼頁，
    該頁正需要本端點顯示正確門檻；掛密碼閘會讓它在最需要的時候拿不到。回應只有兩個門檻數字、
    不含個資，與 `/dp/user/me` 不受密碼閘的理由不同但結論一致。
    """
    rules = await _profile_service.password_rules(db, user_id=payload.sub)
    return ApplicablePasswordPolicyResponse(min_len=rules.min_len, char_types=rules.char_types)


@router.put("/dp/user/me", status_code=status.HTTP_204_NO_CONTENT)
async def update_me(
    data: NameUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> None:
    """變更姓名（直接生效、ET / DM 同步）+ 稽核。"""
    await _profile_service.update_name(db, user_id=operator.user_id, user_name=data.user_name)


@router.put("/dp/user/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
    _ip_limit: None = Depends(rate_limit_by_ip(_pwd_change_limiter, "pwd-change")),
) -> None:
    """變更密碼（含強制變更收尾）：驗舊 + 兩次一致 + 複雜度（特權 12）+ 重複性。

    IP + 帳號雙維度限流（FR-07）；帳號維度先 hit 後執行。
    """
    _pwd_change_limiter.hit(f"pwd-change:acct:{operator.user_id}")
    await _profile_service.change_password(
        db,
        user_id=operator.user_id,
        old_password=data.old_password,
        new_password=data.new_password,
        confirm_password=data.confirm_password,
    )


@router.put("/dp/user/me/email", status_code=status.HTTP_202_ACCEPTED)
async def change_email(
    data: EmailChangeRequest,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
    _ip_limit: None = Depends(rate_limit_by_ip(_email_change_limiter, "email-change")),
) -> dict[str, object]:
    """申請 Email 變更（延遲生效）：唯一檢核 → 產 token + PENDING_EMAIL → 寄驗證信至新信箱。

    寄信冷卻（#74，預設 10 分）：check 於送信前擋、record 於送信成功後蓋章——唯一性失敗（409）
    不誤觸冷卻。成功回應帶 retry_after（＝冷卻秒數）供前端起算倒數。
    """
    _email_change_limiter.hit(f"email-change:acct:{operator.user_id}")
    cooldown_sec = await _params.get_int_param(db, "LOGIN", "VERIFY_SEND_COOLDOWN_SEC", _VERIFY_SEND_COOLDOWN_DEFAULT)
    key = f"email-change-send:acct:{operator.user_id}"
    _email_change_cooldown.check(key, cooldown_sec)
    await _email_change_service.request(db, user_id=operator.user_id, new_email=data.new_email)
    _email_change_cooldown.record(key)
    return {
        "message": "驗證信已寄至新 Email，請於效期內完成驗證；驗證前原 Email 仍可登入",
        "retry_after": cooldown_sec,
    }


@router.post("/verify-email-change")
async def verify_email_change(
    data: EmailChangeVerify,
    db: AsyncSession = Depends(get_db),
    _ip_limit: None = Depends(rate_limit_by_ip(_verify_email_change_limiter, "verify-email-change")),
) -> dict[str, str]:
    """完成 Email 變更（公開，持信中連結 token）：消 token → 切 EMAIL + 稽核。"""
    await _email_change_service.verify(db, token=data.token)
    return {"message": "Email 已變更，請以新 Email 登入"}


@router.get("/password-policy", response_model=PasswordPolicyResponse)
async def get_password_policy(db: AsyncSession = Depends(get_db)) -> PasswordPolicyResponse:
    """公開密碼政策（併 #77 核心）：供變更密碼 / 註冊 / 重設頁動態渲染提示；僅非機密數值、即時不快取。"""
    return PasswordPolicyResponse(
        min_len=await _params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN),
        admin_min_len=await _params.get_int_param(db, "PWD_POLICY", "ADMIN_MIN_LEN", _DEFAULT_ADMIN_MIN_LEN),
        char_types=await _params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES),
        history_count=await _params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT),
        expiry_days=await _params.get_int_param(db, "PWD_POLICY", "EXPIRY_DAYS", _DEFAULT_EXPIRY_DAYS),
    )
