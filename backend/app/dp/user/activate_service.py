"""帳號啟用服務（US4 #67 管理者邀請）。

受邀者點邀請信連結（`/activate?token=...`）進入啟用頁，**自設密碼**啟用帳號。
= US2 verify（消 token、建 DP_USER + 啟用副作用）＋ US3 reset（收密碼、驗複雜度）之合體：
驗 token（僅 ADMIN_INVITE）+ 效期 + 兩次一致 + 複雜度 → 以使用者所設密碼呼叫共用
`activate_pending_account`（建 DP_USER(ACTIVE) + 首筆 PWD_HIST + 授 ET 學員 + 雙稽核 + 刪 pending）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.user.activation import activate_with_new_password
from app.dp.user.kinds import KIND_ADMIN_INVITE
from app.dp.user.repository import AuthRepository
from app.services import AuditLogService, ParamService

_FUNC_NAME = "DP-USERS"
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
_TOKEN_INVALID_MSG = "邀請連結無效"  # noqa: S105 — 使用者訊息，非密碼
_TOKEN_EXPIRED_MSG = "邀請連結已失效，請洽管理者重寄"  # noqa: S105 — 使用者訊息，非密碼


class ActivateAccountService:
    """以邀請 token + 使用者自設密碼啟用帳號（US4）。"""

    def __init__(
        self,
        repository: AuthRepository | None = None,
        audit: AuditLogService | None = None,
        params: ParamService | None = None,
    ) -> None:
        self._repo = repository or AuthRepository()
        self._audit = audit or AuditLogService()
        self._params = params or ParamService()

    async def activate(self, db: AsyncSession, *, token: str, new_password: str, confirm_password: str) -> None:
        """驗邀請 token + 密碼 → 啟用帳號。

        Raises:
            AppError: token 無效 / 非邀請（400 DP_USER_003）、逾期（400 DP_USER_004）、
                兩次不一致（422 DP_USER_002）、密碼不符複雜度（422 DP_PWD_001/002/004）、
                Email 已啟用 / 競態（409 DP_USER_001）。
        """
        await activate_with_new_password(
            db,
            token=token,
            new_password=new_password,
            confirm_password=confirm_password,
            expected_kind=KIND_ADMIN_INVITE,
            repo=self._repo,
            audit=self._audit,
            params=self._params,
            func_name=_FUNC_NAME,
            create_desc="受邀者設定密碼啟用帳號",
            token_invalid_msg=_TOKEN_INVALID_MSG,
            token_expired_msg=_TOKEN_EXPIRED_MSG,
        )
