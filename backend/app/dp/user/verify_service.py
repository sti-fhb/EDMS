"""註冊驗證 / 重寄服務（US2 #56 方案 B）。

VerifyService：驗 token → 建 DP_USER（ACTIVE）+ 啟用副作用（首筆 PWD_HIST + 授 ET 學員 + 雙稽核）
+ 刪待驗證列。啟用副作用只在此驗證步落地（未驗證帳號不先佔角色 / 稽核）。冪等性以 DP_USER
EMAIL 唯一鍵為底層保證：重複 / 競態確認 → 第一個建成、其餘乾淨拒絕（409 DP_USER_001）。

ResendVerificationService：重寄驗證信（僅對 pending 帳號）；作廢舊 token（以 Email 覆蓋）、產新、重寄；
防列舉——無論該 Email 是否有待驗證列，端點一律回相同訊息。
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.user.activation import activate_with_new_password
from app.dp.user.kinds import KIND_SELF_REGISTER
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.services import AuditLogService, NotifyService, ParamService

_TEMPLATE_CODE = "ACCOUNT_VERIFY"
_FUNC_NAME = "DP-REGISTER"
_DEFAULT_TTL_MIN = 30
_TOKEN_INVALID_MSG = "驗證連結無效"  # noqa: S105 — 使用者訊息，非密碼
_TOKEN_EXPIRED_MSG = "驗證連結已失效，請重新申請"  # noqa: S105 — 使用者訊息，非密碼


class VerifyService:
    """以驗證 token 啟用註冊：建 DP_USER + 啟用副作用 + 刪待驗證列。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._audit = audit or AuditLogService()
        self._params = params or ParamService()

    async def verify(self, db: AsyncSession, *, new_password: str, confirm_password: str, token: str) -> None:
        """驗證註冊 token → **由本人當場設定密碼** → 啟用帳號（#212）。

        密碼不再來自 pending 列（該列自 #212 起 PWD_HASH 為 NULL）。原本存「註冊當下填寫者的
        密碼」使任何人可用他人 Email 註冊並填自己的密碼，受害者點下驗證信後帳號即以攻擊者的
        密碼建立（pre-hijack）。改為與 US4 邀請啟用同一實作 `activate_with_new_password`。

        Raises:
            AppError: token 無效（400 DP_USER_003）、逾時（400 DP_USER_004）、兩次不一致
                （422 DP_USER_002）、密碼不符複雜度（422 DP_PWD_001/002/004）、
                Email 已完成驗證 / 競態（409 DP_USER_001）。
        """
        await activate_with_new_password(
            db,
            token=token,
            new_password=new_password,
            confirm_password=confirm_password,
            expected_kind=KIND_SELF_REGISTER,
            repo=self._repo,
            audit=self._audit,
            params=self._params,
            func_name=_FUNC_NAME,
            create_desc="使用者自助註冊（Email 驗證通過並設定密碼）",
            token_invalid_msg=_TOKEN_INVALID_MSG,
            token_expired_msg=_TOKEN_EXPIRED_MSG,
        )


class ResendVerificationService:
    """重寄註冊驗證信（僅對 pending 帳號）；防列舉：一律回相同訊息。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()

    async def resend(self, db: AsyncSession, *, email: str) -> bool:
        """重寄：pending 存在且有效才作廢舊 token、產新並重寄；否則靜默（防列舉）。

        僅處理自助註冊（SELF_REGISTER）；管理者邀請（ADMIN_INVITE）之重寄走使用者管理頁（US4 #67），
        不經此匿名端點，故遇邀請列一律靜默（等同不存在，維持防列舉）。

        Returns:
            bool: **是否真的寄出信**。呼叫端據此決定蓋哪一個冷卻章（#213）——沒寄信卻蓋 Email 章
                會讓任何匿名者無限期封鎖任意 Email 的自助註冊，見 `router._verify_send_probe_key`。
                回傳值刻意**不**影響對外回應（訊息 / 狀態碼 / retry_after 三條路徑皆相同），
                否則會變成 pending 存在性 oracle。
        """
        now = utcnow()
        pending = await self._repo.get_pending_by_email(db, email)
        # 逾期列視同不存在（#212）：原本不檢查 expires_date，導致任何匿名者每 30 分鐘打一次重寄
        # 就能讓一筆註冊申請永遠不死——排程對逾期列的清理因此對被盯上的列失效，且該 Email 的
        # UNIQUE 名額被永久佔住（管理者想邀請該人會撞 409「已被註冊」，訊息完全誤導）。
        # 回應與「不存在」完全相同（同訊息、同狀態碼），故防列舉語意不變；連結逾期的正常使用者
        # 重新註冊即可（#212 之後註冊只需 Email + 姓名，比重寄更簡單）。
        if pending is None or pending.kind != KIND_SELF_REGISTER or pending.expires_date <= now:
            return False

        ttl_min = await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)
        plaintext = generate_reset_token()
        # 以 Email 覆蓋：刪舊列（舊 token 即作廢）→ 沿用原姓名 / 密碼雜湊寫新列。
        # 用條件式刪除（非無條件版）：上面的 kind 檢查到此處之間隔著兩次 DB 讀取與 token 產生，
        # 若該空窗內原 SELF_REGISTER 列被驗證消耗、管理者又對同 Email 發出邀請，無條件刪除會
        # 吃掉那筆新邀請（與 #125 同一個 TOCTOU 形狀）。保留邀請後改由下方 UNIQUE 撞成 409。
        # ⚠️ 與 register_service 的不對稱（刻意）：後者在覆蓋**逾期**邀請時補一筆 DELETE 稽核
        # （#125，供管理者追查邀請為何消失）；本路徑不補——要走到「resend 刪掉逾期邀請」需三方
        # 毫秒級競態，且本服務未持 AuditLogService。日後若要留痕，應與 register_service 對齊。
        await self._repo.delete_pending_unless_active_invite(db, email, now)
        try:
            await self._repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=pending.email,
                user_name=pending.user_name,
                pwd_hash=pending.pwd_hash,
                expires_date=now + timedelta(minutes=ttl_min),
                now=now,
            )
        except IntegrityError as exc:
            # 撞 UQ 的兩條路徑，皆為競態、皆不洩露存在性（攻擊者無法迫使其發生）：
            # (1) 另一交易已搶插同 Email pending；
            # (2) 條件式刪除保留了空窗內出現的**有效**管理者邀請（#137），故插不進去。
            # 轉乾淨 409（交 get_db rollback，避免對失敗 session commit）。
            raise AppError(
                status_code=409, detail="此 Email 註冊處理中，請稍後再試或直接登入", error_code="DP_USER_005"
            ) from exc
        verify_link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={plaintext}"
        await self._notify.send_email(
            db,
            recipients=[email],
            template_code=_TEMPLATE_CODE,
            module="DP",
            params={"user_name": pending.user_name, "verify_link": verify_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )
        return True
