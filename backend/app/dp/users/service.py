"""使用者管理服務（US4）：查詢 / 代建 / 停用 / 啟用 / 解鎖 / 基本資料維護。

帳號建立重用 US2（#56）已落地的 AuthRepository.create_user / add_pwd_history 與
module_provisioning 授學員邏輯，僅差異：operator = 管理者、MUST_CHANGE_PWD = true。
所有 CUD 於同交易內經 SRVDP003（AuditLogService）寫稽核（含 before / after value）。
授權：依暫行規則僅認證、不掛 admin 閘（SA 裁示 Q1=A，待 T049 回歸）。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.operator import OperatorInfo
from app.core.pagination import PaginatedResult, paginate
from app.core.password_policy import hash_password, validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.ids import generate_user_id
from app.dp.user.repository import AuthRepository
from app.dp.users.repository import UsersRepository
from app.dp.users.schemas import UserCreate, UserResponse, UserUpdate
from app.services import AuditLogService, ParamService

_FUNC_NAME = "DP-USERS"
_ET_MODULE = "ET"
_EMAIL_TAKEN_MSG = "此 Email 已被使用"
_NOT_FOUND_MSG = "查無此帳號"
_SELF_PROTECT_MSG = "無法停用或鎖定自己的帳號"
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3


def _iso(value: object) -> object:
    """稽核 before/after 值序列化：datetime → ISO 字串（供 JSONB 儲存），其餘原樣。"""
    return value.isoformat() if hasattr(value, "isoformat") else value


class UsersService:
    """SRVDP 使用者管理服務（US4）。"""

    def __init__(
        self,
        repository: UsersRepository | None = None,
        auth_repository: AuthRepository | None = None,
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or UsersRepository()
        self._auth_repo = auth_repository or AuthRepository()
        self._audit = audit or AuditLogService()
        self._params = params or ParamService()

    async def list_users(
        self, db: AsyncSession, *, keyword: str | None, status: str | None, page: int, limit: int
    ) -> PaginatedResult[UserResponse]:
        """查詢使用者清單（姓名 / Email 關鍵字 + 狀態篩選，後端分頁）。"""
        stmt = self._repo.build_list_stmt(keyword=keyword, status=status, now=utcnow())
        return await paginate(db, stmt, page=page, limit=limit, schema=UserResponse)

    async def create_user(self, db: AsyncSession, *, data: UserCreate, operator: OperatorInfo) -> UserResponse:
        """管理者代建帳號：初始密碼（複雜度）→ 建 DP_USER(ACTIVE, MUST_CHANGE_PWD=true) + 授 ET 學員
        + 首筆 PWD_HIST + 雙稽核。Email 唯一（409 DP_USER_007）。

        Raises:
            AppError: Email 已被使用（409 DP_USER_007）、密碼不符複雜度（422 DP_PWD_001/002/004）。
        """
        if await self._repo.email_taken(db, data.email):
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007")

        min_len = await self._params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
        char_types = await self._params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
        validate_password_strength(data.password, min_length=min_len, required_char_types=char_types)

        now = utcnow()
        ip = get_client_ip()
        user_id = generate_user_id()
        pwd_hash = hash_password(data.password)

        # 建帳號（重用 #56；管理者代建 → MUST_CHANGE_PWD=true、operator=管理者）
        # email_taken 檢查與 flush 之間有 TOCTOU 空窗：並發代建同 Email → 撞 UQ_DP_USER_EMAIL。
        # 比照 verify_service 兜底轉乾淨 409（否則落全域 500），交 get_db rollback。
        try:
            user = await self._auth_repo.create_user(
                db,
                user_id=user_id,
                email=data.email,
                user_name=data.user_name,
                pwd_hash=pwd_hash,
                operator_id=operator.user_id,
                now=now,
                must_change_pwd=True,
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007") from exc
        await self._auth_repo.add_pwd_history(
            db, user_id=user_id, seq_no=1, pwd_hash=pwd_hash, operator_id=operator.user_id, now=now
        )
        await module_provisioning_gate.grant_default_role(_ET_MODULE, user_id, db)
        await self._log(
            db,
            operator.user_id,
            user_id,
            ip,
            "CREATE",
            "管理者代建帳號",
            after={"email": data.email, "user_name": data.user_name, "status": "ACTIVE", "must_change_pwd": True},
        )
        await self._log(db, operator.user_id, user_id, ip, "CREATE", "授予預設 ET 學員角色")
        return UserResponse.model_validate(user)

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
        """維護基本資料（姓名 / Email 直接生效，不走驗證信）。Email 唯一（排除自己）。

        Raises:
            AppError: 帳號不存在（404 DP_USER_008）、Email 已被使用（409 DP_USER_007）。
        """
        user = await self._require_user(db, user_id)
        if await self._repo.email_taken(db, data.email, exclude_user_id=user_id):
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007")

        before = {"user_name": user.user_name, "email": user.email}
        now = utcnow()
        # 同 create：email_taken 與 flush 間 TOCTOU 空窗 → 撞 UQ 兜底轉 409
        try:
            await self._repo.update_basic(
                db, user=user, user_name=data.user_name, email=data.email, operator_id=operator.user_id, now=now
            )
        except IntegrityError as exc:
            raise AppError(status_code=409, detail=_EMAIL_TAKEN_MSG, error_code="DP_USER_007") from exc
        await self._log(
            db,
            operator.user_id,
            user_id,
            get_client_ip(),
            "UPDATE",
            "維護帳號基本資料",
            before=before,
            after={"user_name": data.user_name, "email": data.email},
        )
        return UserResponse.model_validate(user)

    async def _require_user(self, db: AsyncSession, user_id: str):
        """載入使用者，不存在拋 404 DP_USER_008。"""
        user = await self._repo.get_by_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_USER_008")
        return user

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
