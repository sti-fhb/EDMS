"""註冊服務（US2 自助註冊）。

伺服器端檢核（兩次一致 / Email 唯一 / 密碼複雜度）→ 建 DP_USER（bcrypt、ACTIVE）
+ 首筆 DP_PWD_HIST（後續重複性檢核基準）+ 授 ET 學員（module-callbacks §2，stub 先行）
+ 雙稽核（帳號 CREATE + 角色授予，皆 MODULE=DP、operator=新使用者本人）。
複雜度門檻讀平台級 DP_PARAM（SRVDP001）；一般使用者用 MIN_LEN / CHAR_TYPES（不套 ADMIN_MIN_LEN）。

稽核歸屬與 operator_id 依 spec_us2 Clarifications 2026-07-20（角色授予由 DP 端寫；operator = 本人）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_policy import hash_password, validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.ids import generate_user_id
from app.dp.user.repository import AuthRepository
from app.services import AuditLogService, ParamService

_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
_FUNC_NAME = "DP-REGISTER"
_ET_MODULE = "ET"


class RegisterService:
    """SRVDP 自助註冊服務（US2）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def register(
        self, db: AsyncSession, *, email: str, user_name: str, password: str, confirm_password: str
    ) -> None:
        """自助註冊：檢核 → 建帳號 + 首筆歷程 + 授 ET 學員 + 雙稽核。

        提交由 get_db 於請求成功時負責；任一檢核失敗於寫入前拋 AppError，get_db rollback 無副作用。

        Raises:
            AppError: 兩次不一致（422 DP_USER_002）、Email 重複（409 DP_USER_001）、
                密碼不符複雜度（422 DP_PWD_001/002/004）。
        """
        ip = get_client_ip()
        # 1. 兩次一致（FR-02 要求伺服器端權威檢核，前端 Zod 另擋一次）
        if password != confirm_password:
            raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")
        # 2. Email 唯一
        if await self._repo.email_exists(db, email):
            raise AppError(
                status_code=409,
                detail="此 Email 已被註冊，請直接登入或使用忘記密碼",
                error_code="DP_USER_001",
            )
        # 3. 密碼複雜度（一般使用者；validate_password_strength 拋 DP_PWD_001/002/004）
        min_len = await self._int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
        char_types = await self._int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
        validate_password_strength(password, min_length=min_len, required_char_types=char_types)

        # 4. 建帳號（bcrypt、ACTIVE）；operator = 新使用者本人 USER_ID
        now = utcnow()
        user_id = generate_user_id()
        pwd_hash = hash_password(password)
        await self._repo.create_user(
            db, user_id=user_id, email=email, user_name=user_name, pwd_hash=pwd_hash, operator_id=user_id, now=now
        )
        # 5. 首筆密碼歷程（SEQ_NO=1）
        await self._repo.add_pwd_history(db, user_id=user_id, seq_no=1, pwd_hash=pwd_hash, operator_id=user_id, now=now)
        # 6. 授 ET 學員（stub 先行；已註冊模組授予失敗會傳播 → 整筆交易回滾）
        await module_provisioning_gate.grant_default_role(_ET_MODULE, user_id, db)
        # 7. 雙稽核（皆 MODULE=DP、CREATE、operator=本人；以 description 區分帳號建立與角色授予）
        await self._audit_register(db, user_id, ip, "使用者自助註冊")
        await self._audit_register(db, user_id, ip, "授予預設 ET 學員角色")
        await db.flush()

    async def _int_param(self, db: AsyncSession, param_id: str, key: str, default: int) -> int:
        raw = await self._params.get_param_value(db, param_id, key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def _audit_register(self, db: AsyncSession, user_id: str, ip: str | None, desc: str) -> None:
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=user_id,
            target_id=user_id,
            description=desc,
            source_ip=ip,
        )
