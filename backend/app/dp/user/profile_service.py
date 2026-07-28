"""個人資料服務（US8）：姓名變更與密碼變更（/me 自助端點）。

所有登入者維護**自己的**資料。姓名直接存（ET / DM 共用 DP_USER）；密碼變更驗舊 + 複雜度
（特權 12）+ 重複性 + 追加歷程 + 清 MUST_CHANGE_PWD + 稽核。門檻值讀平台級 PWD_POLICY（SRVDP001）；
特權門檻依 is_module_admin（T017，過渡期 fail-closed → 一律套一般 8，特權 12 待 T049）。

強制變更密碼（US1 逾效期 / 初始密碼）沿用 change_password 同一路徑——仍需舊密碼。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.password_policy import (
    hash_password,
    is_reused,
    validate_password_strength,
    verify_password,
)
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.repository import AuthRepository
from app.dp.users.models import DpUser
from app.services import AuditLogService, ParamService

_FUNC_NAME = "DP-PROFILE"
_DEFAULT_MIN_LEN = 8
_DEFAULT_ADMIN_MIN_LEN = 12
_DEFAULT_CHAR_TYPES = 3
_DEFAULT_HISTORY_COUNT = 3


class ProfileService:
    """個人資料維護（US8 T037）：姓名變更、密碼變更（含強制變更收尾）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        params: ParamService | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._params = params or ParamService()
        self._audit = audit or AuditLogService()

    async def get_me(self, db: AsyncSession, *, user_id: str) -> DpUser:
        """讀本人個人資料（姓名 / Email / PENDING_EMAIL）。

        Raises:
            AppError: 查無帳號（404 DP_USER_008）；認證後理論上必存在，為型別安全仍防呆。
        """
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail="查無此帳號", error_code="DP_USER_008")
        return user

    async def update_name(self, db: AsyncSession, *, user_id: str, user_name: str) -> None:
        """更新姓名（直接生效，ET / DM 同步）並寫稽核（含前後值）。

        Raises:
            AppError: 查無帳號（404 DP_USER_008）。
        """
        now = utcnow()
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail="查無此帳號", error_code="DP_USER_008")
        before = user.user_name
        await self._repo.update_name(db, user=user, user_name=user_name, operator_id=user_id, now=now)
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user_id,
            target_id=user_id,
            description="姓名變更",
            before_value={"user_name": before},
            after_value={"user_name": user_name},
            source_ip=get_client_ip(),
        )

    async def change_password(
        self, db: AsyncSession, *, user_id: str, old_password: str, new_password: str, confirm_password: str
    ) -> None:
        """變更密碼：驗舊 + 兩次一致 + 複雜度（特權 12）+ 重複性 → 更新 + 歷程 + 清 MUST_CHANGE + 稽核。

        Raises:
            AppError: 查無帳號（404 DP_USER_008）、舊密碼錯（401 DP_AUTH_008）、兩次不一致（422 DP_USER_002）、
                複雜度（422 DP_PWD_001/002）、重複性（422 DP_PWD_003）。
        """
        now = utcnow()
        user = await self._repo.get_by_user_id(db, user_id)
        if user is None:
            raise AppError(status_code=404, detail="查無此帳號", error_code="DP_USER_008")

        # 舊密碼錯用 422（非 401）：401 於前端 http interceptor 代表「session 失效 → 自動登出」，
        # 若舊密碼錯回 401 會被誤判為逾時而登出、吞掉「舊密碼不正確」訊息（US8 手測發現）。
        if not verify_password(old_password, user.pwd_hash):
            raise AppError(status_code=422, detail="舊密碼不正確", error_code="DP_PWD_006")
        if new_password != confirm_password:
            raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")

        min_len = await self._resolve_min_len(db, user_id)
        char_types = await self._params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
        validate_password_strength(new_password, min_length=min_len, required_char_types=char_types)
        history_count = await self._params.get_int_param(db, "PWD_POLICY", "HISTORY_COUNT", _DEFAULT_HISTORY_COUNT)
        recent = await self._repo.recent_pwd_hashes(db, user_id, history_count)
        if is_reused(new_password, recent):
            raise AppError(status_code=422, detail="不可與最近使用過之密碼相同", error_code="DP_PWD_003")

        new_hash = hash_password(new_password)
        await self._repo.update_password(db, user=user, pwd_hash=new_hash, operator_id=user_id, now=now)
        seq_no = await self._repo.next_pwd_seq_no(db, user_id)
        await self._repo.add_pwd_history(
            db, user_id=user_id, seq_no=seq_no, pwd_hash=new_hash, operator_id=user_id, now=now
        )
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=user_id,
            target_id=user_id,
            description="密碼變更",  # 稽核不記密碼前後值（sti-backend-logging）
            source_ip=get_client_ip(),
        )

    async def _resolve_min_len(self, db: AsyncSession, user_id: str) -> int:
        """決定密碼最小長度：特權帳號（ET / DM 任一管理者）套 ADMIN_MIN_LEN，否則 MIN_LEN。

        is_module_admin 過渡期 fail-closed（未接線回 False）→ 一律套一般門檻，特權 12 待 T049。
        """
        is_privileged = await module_admin_gate.is_module_admin(
            "ET", user_id, db
        ) or await module_admin_gate.is_module_admin("DM", user_id, db)
        if is_privileged:
            return await self._params.get_int_param(db, "PWD_POLICY", "ADMIN_MIN_LEN", _DEFAULT_ADMIN_MIN_LEN)
        return await self._params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
