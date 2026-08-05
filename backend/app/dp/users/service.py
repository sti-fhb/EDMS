"""使用者管理服務（US4，#67 代建改邀請流程）：查詢 / 邀請建立 / 待啟用邀請維護 / 停用 / 啟用 / 解鎖 / 姓名維護。

建立帳號改為**邀請連結信**：管理者僅填 Email / 姓名，寫 `DP_PENDING_REGISTRATION`
（`kind=ADMIN_INVITE`、`pwd_hash=NULL`）並寄邀請信；**不建 DP_USER、不授角色**——使用者點連結
自設密碼後才由 `activate_pending_account` 落地啟用副作用。重寄 / 取消邀請亦為管理者動作。
所有 CUD 於同交易內經 SRVDP003（AuditLogService）寫稽核（含 before / after value）。
授權：依暫行規則僅認證、不掛 admin 閘（SA 裁示 Q1=A，待 T049 回歸）。
"""

import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cooldown import VerifySendCooldown
from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.pagination import PaginatedResult, paginate
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.ids import generate_user_id
from app.dp.user.repository import AuthRepository
from app.dp.user.token import generate_reset_token, hash_token
from app.dp.users.repository import UsersRepository
from app.dp.users.schemas import InviteResponse, UserCreate, UserResponse, UserUpdate
from app.services import AuditLogService, NotifyService, ParamService

logger = logging.getLogger(__name__)

_FUNC_NAME = "DP-USERS"
_INVITE_TEMPLATE = "ACCOUNT_INVITE"
_PWD_EXPIRY_TEMPLATE = "PWD_EXPIRY_REMIND"  # noqa: S105 — 通知範本代碼，非密碼
_KIND_ADMIN_INVITE = "ADMIN_INVITE"
_SYSTEM_USER = "SYSTEM"
_PENDING_INVITE_MSG = "此 Email 已有待啟用邀請，請改用重寄"
_EMAIL_TAKEN_MSG = "此 Email 已被使用"
_NOT_FOUND_MSG = "查無此帳號"
_INVITE_NOT_FOUND_MSG = "查無此邀請"
_SELF_PROTECT_MSG = "無法停用或鎖定自己的帳號"
_DEFAULT_TTL_MIN = 30


def _iso(value: object) -> object:
    """稽核 before/after 值序列化：datetime → ISO 字串（供 JSONB 儲存），其餘原樣。"""
    return value.isoformat() if hasattr(value, "isoformat") else value


def _send_cooldown_key(email: str) -> str:
    """建立 / 重新邀請的冷卻分桶鍵（Email 維度）。"""
    return f"invite:send:{email}"


class UsersService:
    """SRVDP 使用者管理服務（US4）。"""

    def __init__(
        self,
        repository: UsersRepository | None = None,
        auth_repository: AuthRepository | None = None,
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
        notify: NotifyService | None = None,
        invite_cooldown: VerifySendCooldown | None = None,
    ) -> None:
        self._repo = repository or UsersRepository()
        self._auth_repo = auth_repository or AuthRepository()
        self._audit = audit or AuditLogService()
        self._params = params or ParamService()
        self._notify = notify or NotifyService()
        # 行程內冷卻狀態；由 router 以模組級單例注入（存活於整個 app 生命週期），測試各自新建即天然隔離
        self._invite_cooldown = invite_cooldown or VerifySendCooldown()

    async def list_users(
        self, db: AsyncSession, *, keyword: str | None, status: str | None, page: int, limit: int
    ) -> PaginatedResult[UserResponse]:
        """查詢正式帳號清單（DP_USER；姓名 / Email 關鍵字 + 狀態篩選，後端分頁）。"""
        stmt = self._repo.build_list_stmt(keyword=keyword, status=status, now=utcnow())
        return await paginate(db, stmt, page=page, limit=limit, schema=UserResponse)

    async def create_user(self, db: AsyncSession, *, data: UserCreate, operator: OperatorInfo) -> None:
        """管理者建立帳號＝寄邀請信（#67）：檢 Email 未被佔用 → 寫 pending（ADMIN_INVITE、pwd_hash=NULL）
        + 寄 ACCOUNT_INVITE 邀請信 + 稽核。**不建 DP_USER、不授角色**（啟用時才落地）。

        重複 Email 分四種情況（#111）：
        - 已啟用（DP_USER 存在）→ 409 DP_USER_007（真重複）。
        - 待啟用列存在但**非 ADMIN_INVITE**（使用者自助註冊中）→ 409 DP_USER_007（維持既有語意）。
        - 待啟用邀請**未逾期** → 409 DP_USER_010（引導改用重寄）。
        - 待啟用邀請**已逾期** → 視為**重新邀請**：沿用原 res_id、作廢舊列、換新 token/效期並重寄。

        Raises:
            AppError: Email 已被啟用帳號 / 自助註冊佔用（409 DP_USER_007）；已有未逾期待啟用邀請
                （409 DP_USER_010）；重新邀請仍在寄信冷卻內（429 COMMON_429）。
        """
        if await self._auth_repo.email_exists(db, data.email):
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007")

        now = utcnow()
        existing = await self._auth_repo.get_pending_by_email(db, data.email)
        if existing is not None and existing.kind != _KIND_ADMIN_INVITE:
            # 自助註冊（SELF_REGISTER）處理中：該列不在邀請清單（build_invite_list_stmt 濾 kind）、
            # res_id 為 NULL，管理者既無可重寄對象也不應覆蓋他人註冊列，故維持「Email 已被使用」
            # 而非回 DP_USER_010（會把管理者導向不存在的重寄動作）。
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007")

        reinvite = existing is not None
        before: dict | None = None
        if existing is not None:
            if existing.expires_date > now:
                # 未逾期：已有處理中的待啟用邀請，引導改用重寄（與「已啟用」的 007 區分）
                raise AppError(status_code=409, detail=_PENDING_INVITE_MSG, error_code="DP_USER_010")
            # 逾期重新邀請＝對同一信箱再寄一封（等同重寄），故套用與 resend 相同的冷卻政策。
            # 冷卻檢查刻意置於「已確定走重新邀請」之後：若前置於 router，未逾期的重複建立會被 429
            # 蓋掉 AC1 要求的 409 DP_USER_010，反而失去「請改用重寄」的導引作用。
            self._invite_cooldown.check(_send_cooldown_key(data.email), settings.INVITE_RESEND_COOLDOWN_SEC)
            # 舊列快照須在刪除前取（供稽核 before），避免刪後讀到過期狀態
            before = {
                "user_name": existing.user_name,
                "kind": existing.kind,
                "expires_date": _iso(existing.expires_date),
            }
            # 沿用原 res_id（識別碼穩定），作廢舊列後重寫
            res_id = existing.res_id or generate_user_id()
            await self._auth_repo.delete_pending_by_email(db, data.email)
        else:
            res_id = generate_user_id()

        ip = get_client_ip()
        plaintext = generate_reset_token()
        ttl_min = await self._invite_ttl_min(db)
        expires_date = now + timedelta(minutes=ttl_min)

        # check→insert 間 TOCTOU 空窗：並發同 Email → 撞 UQ_DP_PENDING_REGISTRATION_EMAIL，兜底轉 409
        try:
            await self._auth_repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=data.email,
                user_name=data.user_name,
                pwd_hash=None,
                expires_date=expires_date,
                now=now,
                kind=_KIND_ADMIN_INVITE,
                res_id=res_id,
                operator_id=operator.user_id,
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007") from exc

        await self._send_invite(db, email=data.email, user_name=data.user_name, token=plaintext, ttl_min=ttl_min)
        # 每次成功寄出都蓋章（含首次邀請）：冷卻起點才能涵蓋「首寄 → 逾期後重新邀請」的間隔
        self._invite_cooldown.record(_send_cooldown_key(data.email))
        await self._log(
            db,
            operator.user_id,
            res_id,
            ip,
            # 重新邀請本質為「刪舊列 + 寫新列 + 重寄」，與 resend_invite 同性質，故同記 UPDATE
            "UPDATE" if reinvite else "CREATE",
            "逾期重新邀請（等同重寄）" if reinvite else "管理者發出帳號邀請",
            before=before,
            after={
                "email": data.email,
                "user_name": data.user_name,
                "kind": _KIND_ADMIN_INVITE,
                "expires_date": _iso(expires_date),
            },
        )

    async def list_invites(
        self, db: AsyncSession, *, keyword: str | None, page: int, limit: int
    ) -> PaginatedResult[InviteResponse]:
        """查詢待啟用邀請清單（DP_PENDING_REGISTRATION，僅 ADMIN_INVITE，後端分頁）。"""
        stmt = self._auth_repo.build_invite_list_stmt(keyword=keyword)
        return await paginate(db, stmt, page=page, limit=limit, schema=InviteResponse)

    async def resend_invite(self, db: AsyncSession, *, res_id: str, operator: OperatorInfo) -> None:
        """重寄邀請：作廢舊 token、產新並重寄（沿用同 res_id / Email / 姓名）。

        Raises:
            AppError: 邀請不存在（404 DP_USER_009）。
        """
        invite = await self._require_invite(db, res_id)
        now = utcnow()
        ip = get_client_ip()
        plaintext = generate_reset_token()
        ttl_min = await self._invite_ttl_min(db)
        # 以 Email 覆蓋：刪舊列（舊 token 即作廢）→ 沿用原 res_id / 姓名寫新列
        await self._auth_repo.delete_pending_by_email(db, invite.email)
        try:
            await self._auth_repo.create_pending_registration(
                db,
                token_hash=hash_token(plaintext),
                email=invite.email,
                user_name=invite.user_name,
                pwd_hash=None,
                expires_date=now + timedelta(minutes=ttl_min),
                now=now,
                kind=_KIND_ADMIN_INVITE,
                res_id=res_id,
                operator_id=operator.user_id,
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007") from exc
        await self._send_invite(db, email=invite.email, user_name=invite.user_name, token=plaintext, ttl_min=ttl_min)
        await self._log(
            db,
            operator.user_id,
            res_id,
            ip,
            "UPDATE",
            "重寄帳號邀請",
            after={"email": invite.email, "user_name": invite.user_name},
        )

    async def cancel_invite(self, db: AsyncSession, *, res_id: str, operator: OperatorInfo) -> None:
        """取消邀請：刪除該待邀請列（硬刪）。

        Raises:
            AppError: 邀請不存在（404 DP_USER_009）。
        """
        invite = await self._require_invite(db, res_id)
        await self._auth_repo.delete_pending_by_email(db, invite.email)
        await self._log(
            db,
            operator.user_id,
            res_id,
            get_client_ip(),
            "DELETE",
            "取消帳號邀請",
            before={"email": invite.email, "user_name": invite.user_name},
        )

    async def set_status(self, db: AsyncSession, *, user_id: str, action: str, operator: OperatorInfo) -> UserResponse:
        """停用 / 啟用帳號。停用有自我保護（不可停用自己，403 DP_USER_006）。

        action 已由 UserStatusUpdate（Literal）收斂為 disable / enable，非法值於 422 擋下。

        Raises:
            AppError: 帳號不存在（404 DP_USER_008）、停用自己（403 DP_USER_006）。
        """
        if action == "disable" and user_id == operator.user_id:
            raise AppError(status_code=403, detail=_SELF_PROTECT_MSG, error_code="DP_USER_006")

        user = await self._require_user(db, user_id)
        before = {"status": user.status}
        new_status = "DISABLED" if action == "disable" else "ACTIVE"
        now = utcnow()
        await self._repo.set_status(db, user=user, status=new_status, operator_id=operator.user_id, now=now)
        await self._log(
            db,
            operator.user_id,
            user_id,
            get_client_ip(),
            "UPDATE",
            "停用帳號" if action == "disable" else "啟用帳號",
            before=before,
            after={"status": new_status},
        )
        return UserResponse.model_validate(user)

    async def unlock(self, db: AsyncSession, *, user_id: str, operator: OperatorInfo) -> UserResponse:
        """解鎖帳號：登入失敗計數歸零 + 解除鎖定。

        Raises:
            AppError: 帳號不存在（404 DP_USER_008）。
        """
        user = await self._require_user(db, user_id)
        before = {"login_fail_count": user.login_fail_count, "locked_until": _iso(user.locked_until)}
        now = utcnow()
        await self._repo.unlock(db, user=user, operator_id=operator.user_id, now=now)
        await self._log(
            db,
            operator.user_id,
            user_id,
            get_client_ip(),
            "UPDATE",
            "解鎖帳號",
            before=before,
            after={"login_fail_count": 0, "locked_until": None},
        )
        return UserResponse.model_validate(user)

    async def update_basic(
        self, db: AsyncSession, *, user_id: str, data: UserUpdate, operator: OperatorInfo
    ) -> UserResponse:
        """維護基本資料（#67）：僅更新**姓名**；Email 為登入帳號、唯讀不可代改。

        Raises:
            AppError: 帳號不存在（404 DP_USER_008）。
        """
        user = await self._require_user(db, user_id)
        before = {"user_name": user.user_name}
        now = utcnow()
        await self._repo.update_name(db, user=user, user_name=data.user_name, operator_id=operator.user_id, now=now)
        await self._log(
            db,
            operator.user_id,
            user_id,
            get_client_ip(),
            "UPDATE",
            "維護帳號姓名",
            before=before,
            after={"user_name": data.user_name},
        )
        return UserResponse.model_validate(user)

    # ── 平台每日排程 SCHDP001（US11）：閒置禁用 + 密碼到期提醒 ─────────────
    # 由 app.dp.schedules handler（daily_platform_job）呼叫；operator=SYSTEM、逐筆容錯（savepoint）。

    async def disable_idle_accounts(self, db: AsyncSession) -> int:
        """閒置逾 `LOGIN.IDLE_DISABLE_DAYS`（預設 90）之啟用帳號自動禁用 + 稽核（`func_name=DP-USERS`）。

        從未登入者以 CREATED_DATE 為基準（見 repository.find_idle_active）。**逐筆各自 commit**：
        單一帳號失敗 rollback 不擋其餘，且每筆結束即釋放稽核 chain 之 advisory xact lock（避免整批
        持鎖阻塞並行登入稽核）。回傳成功禁用筆數。
        """
        idle_days = await self._params.get_int_param(db, "LOGIN", "IDLE_DISABLE_DAYS", 90)
        now = utcnow()
        idle_before = now - timedelta(days=idle_days)
        users = await self._repo.find_idle_active(db, idle_before=idle_before)

        disabled = 0
        for user in users:
            try:
                await self._repo.set_status(db, user=user, status="DISABLED", operator_id=_SYSTEM_USER, now=now)
                await self._audit.log_action(
                    db,
                    module="DP",
                    func_name=_FUNC_NAME,
                    action_type="UPDATE",
                    result="SUCCESS",
                    operator_id=_SYSTEM_USER,
                    target_id=user.user_id,
                    description=f"閒置逾 {idle_days} 日自動禁用",
                    before_value={"status": "ACTIVE"},
                    after_value={"status": "DISABLED"},
                )
                await db.commit()
                disabled += 1
            except Exception:
                await db.rollback()
                logger.exception("SCHDP001 閒置禁用失敗 user_id=%s", user.user_id)
        return disabled

    async def send_pwd_expiry_reminders(self, db: AsyncSession) -> int:
        """密碼將於 `EXPIRY_REMIND_DAYS`（預設 7）天內到期之啟用帳號經 SRVDP002 寄 `PWD_EXPIRY_REMIND`。

        每日跑均寄（不去重，spec_us11 FR-05）；**逐筆各自 commit**、失敗 rollback 不擋其餘。回傳寄出筆數。
        """
        expiry_days = await self._params.get_int_param(db, "PWD_POLICY", "EXPIRY_DAYS", 90)
        remind_days = await self._params.get_int_param(db, "PWD_POLICY", "EXPIRY_REMIND_DAYS", 7)
        now = utcnow()
        not_expired_after = now - timedelta(days=expiry_days)
        remind_on_or_before = now - timedelta(days=expiry_days - remind_days)
        users = await self._repo.find_pwd_expiring(
            db, not_expired_after=not_expired_after, remind_on_or_before=remind_on_or_before
        )

        sent = 0
        for user in users:
            expiry_date = user.pwd_changed_date + timedelta(days=expiry_days)
            days_left = max((expiry_date - now).days, 0)
            try:
                await self._notify.send_email(
                    db,
                    recipients=[user.email],
                    template_code=_PWD_EXPIRY_TEMPLATE,
                    module="DP",
                    params={
                        "user_name": user.user_name,
                        "expiry_date": expiry_date.strftime("%Y-%m-%d"),
                        "days_left": str(days_left),
                    },
                    caller_module="DP",
                )
                await db.commit()
                sent += 1
            except Exception:
                await db.rollback()
                logger.exception("SCHDP001 密碼到期提醒寄送失敗 user_id=%s", user.user_id)
        return sent

    async def _invite_ttl_min(self, db: AsyncSession) -> int:
        """邀請 / 重寄連結效期（分鐘）。

        值域下限由參數維護的寫入驗證把關（param_rules 之 `LOGIN.RESET_TOKEN_TTL_MIN` = IntRule(1)），
        此處不再重複夾制——依 sti-coding-style「不為不存在的情境寫防禦碼」。
        """
        return await self._params.get_int_param(db, "LOGIN", "RESET_TOKEN_TTL_MIN", _DEFAULT_TTL_MIN)

    async def _send_invite(self, db: AsyncSession, *, email: str, user_name: str, token: str, ttl_min: int) -> None:
        """寄帳號邀請信（ACCOUNT_INVITE，US6 發信引擎）；連結以設定檔組（防 Host 注入）。"""
        activate_link = f"{settings.FRONTEND_BASE_URL}/activate?token={token}"
        await self._notify.send_email(
            db,
            recipients=[email],
            template_code=_INVITE_TEMPLATE,
            module="DP",
            params={"user_name": user_name, "activate_link": activate_link, "expiry_minutes": str(ttl_min)},
            caller_module="DP",
        )

    async def _require_user(self, db: AsyncSession, user_id: str):
        """載入使用者，不存在拋 404 DP_USER_008。"""
        user = await self._repo.get_by_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_USER_008")
        return user

    async def _require_invite(self, db: AsyncSession, res_id: str):
        """載入待啟用邀請，不存在拋 404 DP_USER_009。"""
        invite = await self._auth_repo.get_invite_by_res_id(db, res_id)
        if invite is None:
            raise AppError(status_code=404, detail=_INVITE_NOT_FOUND_MSG, error_code="DP_USER_009")
        return invite

    async def _log(
        self,
        db: AsyncSession,
        operator_id: str,
        target_id: str,
        ip: str | None,
        action_type: str,
        description: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=target_id,
            description=description,
            before_value=before,
            after_value=after,
            source_ip=ip,
        )
