"""註冊服務（US2 自助註冊，#56 方案 B：Email 驗證後啟用）。

伺服器端檢核（兩次一致 / Email 未被已驗證帳號佔用 / 密碼複雜度）→ **不建 DP_USER**，
改寫入待驗證表 `DP_PENDING_REGISTRATION`（Email / 姓名 / 密碼雜湊 + 一次性驗證 token）
並經發信服務（US6）寄「註冊驗證信」。點驗證連結通過後才由 verify_service 建 DP_USER。

一 Email 一筆待驗證：Email 已在 pending（未驗證）→ 覆蓋（刪舊列 + 新 token + 重寄）＝新註冊語意；
Email 已在 DP_USER（已驗證）→ 409（引導登入 / 忘記密碼）。明文 token 僅入信中連結、DB 存 SHA-256。
複雜度門檻讀平台級 DP_PARAM（一般使用者 MIN_LEN / CHAR_TYPES）；驗證 TTL 沿用既有 token 30 分。
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.kinds import KIND_ADMIN_INVITE
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_EMAIL_TAKEN_MSG = "此 Email 已被註冊，請直接登入或使用忘記密碼"
# 措辭刻意不提「管理者邀請」：本端點為公開匿名，不對外揭露組織脈絡（該句型亦常被釣魚信複用）。
# 認證後的管理者端點（DP_USER_010）則可明說，此不對稱為刻意設計。
_INVITE_PENDING_MSG = "此 Email 已有待完成的帳號啟用程序，請至信箱收取信件完成啟用"
_TEMPLATE_CODE = "ACCOUNT_VERIFY"
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_TTL_MIN = 30
_FUNC_NAME = "DP-REGISTER"
_SYSTEM_USER = "SYSTEM"


class RegisterService:
    """SRVDP 自助註冊服務（US2）：檢核 → 寫待驗證表 + 寄驗證信（不建 DP_USER）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()
        self._audit = audit or AuditLogService()

    async def assert_email_not_registered(self, db: AsyncSession, email: str) -> None:
        """Email 已被「已驗證帳號」佔用 → 409 DP_USER_001；未佔用則靜默通過。

        供 router 在「驗證信寄送冷卻」**之前**呼叫（#86）：「已是正式帳號」是終局狀態，
        等冷卻倒數結束也不會改變，先擋掉可免使用者白等一輪才被告知「已被註冊」。
        對已驗證帳號本來就直接 409、不會送信，冷卻在此無防狂發價值。

        register() 內部亦呼叫本方法（單一 409 來源），故服務層獨立呼叫時語意不變。
        """
        if await self._repo.email_exists(db, email):
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_001")

    async def register(self, db: AsyncSession, *, email: str, user_name: str) -> None:
        """自助註冊：檢核 → 寫待驗證表 + 寄驗證信；**不建 DP_USER、不授角色、不收密碼**。

        密碼於 Email 驗證通過後由本人當場設定（#212，比照 US4 邀請啟用）——原本在此收密碼並
        存入 pending 列，使任何人可用他人 Email 註冊並填自己的密碼，受害者點下驗證信後帳號即
        以攻擊者的密碼建立（pre-hijack）。本方法因此**完全不做 bcrypt**，順帶讓註冊端點不再是
        密碼運算的放大器（#214）。

        稽核：註冊本身不記（帳號尚不存在，紀錄移至驗證步）。**兩個例外**皆為「覆蓋既有 pending
        列」時留痕：逾期的管理者邀請（#125——該列由管理者建立，若被匿名註冊無痕抹除，管理者只
        會發現邀請消失卻查不到原因）、以及既有的自助註冊列（#212——覆蓋會作廢他人的驗證連結並
        換掉姓名，客服需查得到）。

        提交由 get_db 於請求成功時負責；任一檢核失敗於寫入前拋 AppError，get_db rollback 無副作用。

        Raises:
            AppError: Email 已被已驗證帳號佔用（409 DP_USER_001）、該 Email 有未逾期的管理者
                邀請（409 DP_USER_011）、並發競態（409 DP_USER_005）。
        """
        # 1. Email 未被「已驗證帳號」佔用（未驗證的 pending 列於 step 3 覆蓋，不擋）
        await self.assert_email_not_registered(db, email)
        # 1-1. 不得覆蓋管理者發出且仍有效的邀請（#125）。step 3 的覆蓋不分 kind，若不在此擋下，
        #      自助註冊會刪掉管理者的邀請列（該列從邀請清單消失、原邀請信連結失效），且管理者
        #      毫無感知。逾期的邀請則放行覆蓋——邀請既已失效，不應讓該 Email 被永久佔住。
        now = utcnow()
        pending = await self._repo.get_pending_by_email(db, email)
        if pending is not None and pending.kind == KIND_ADMIN_INVITE and pending.expires_date > now:
            raise AppError(status_code=409, detail=_INVITE_PENDING_MSG, error_code="DP_USER_011")

        # 2. 覆蓋同 Email 舊待驗證列（重新註冊 / 重寄語意）→ 寫新待驗證列（僅存 token SHA-256、
        #    PWD_HASH 留空，密碼於驗證步當場設定）
        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        plaintext = generate_reset_token()
        # 條件式刪除：保留 TOCTOU 空窗內剛產生的有效邀請，讓其撞 UNIQUE 轉 409 而非被靜默覆蓋（#125）
        await self._repo.delete_pending_unless_active_invite(db, email, now)
        if pending is not None and pending.kind == KIND_ADMIN_INVITE:
            # 走到這裡代表該邀請已逾期（未逾期者已於 step 2-1 擋下）。覆蓋是 #125 的預期行為
            # （不讓 Email 被永久佔住），但仍須留痕供管理者追查邀請為何消失。
            # operator 記 SYSTEM：行為人為匿名註冊者、無 user_id，且非管理者所為。
            await self._audit.log_action(
                db,
                module="DP",
                func_name=_FUNC_NAME,
                action_type="DELETE",
                result="SUCCESS",
                operator_id=_SYSTEM_USER,
                target_id=pending.invite_id,
                description="逾期管理者邀請被自助註冊覆蓋",
                before_value={
                    "kind": pending.kind,
                    "user_name": pending.user_name,
                    "expires_date": pending.expires_date.isoformat(),
                },
                source_ip=get_client_ip(),
            )
        elif pending is not None:
            # 覆蓋既有自助註冊列（#212）：作廢他人仍有效的驗證連結並換掉姓名。修法 B 之後這已
            # 不構成帳號接管（列裡沒有密碼），但使用者會發現連結突然失效、客服需查得到原因。
            # email 依既有慣例放 before_value（比照 email_change_service），不放 target_id。
            await self._audit.log_action(
                db,
                module="DP",
                func_name=_FUNC_NAME,
                action_type="DELETE",
                result="SUCCESS",
                operator_id=_SYSTEM_USER,
                description="既有自助註冊申請被新的註冊申請覆蓋",
                before_value={
                    "kind": pending.kind,
                    "email": pending.email,
                    "user_name": pending.user_name,
                    "expires_date": pending.expires_date.isoformat(),
                },
                source_ip=get_client_ip(),
            )
        try:
            await self._repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=email,
                user_name=user_name,
                pwd_hash=None,
                expires_date=now + timedelta(minutes=ttl_min),
                now=now,
            )
        except IntegrityError as exc:
            # 同 Email 並發註冊 / 重寄競態：delete 後另一交易已搶插同 Email pending → 撞 UQ。
            # 轉乾淨 409（避免落通用 500）；使用者稍後重試或改走登入。
            raise AppError(
                status_code=409, detail="此 Email 註冊處理中，請稍後再試或直接登入", error_code="DP_USER_005"
            ) from exc
        # 5. 寄驗證信（US6；範本 MODULE=DP ACCOUNT_VERIFY）；連結以設定檔組（防 Host 注入）
        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )
