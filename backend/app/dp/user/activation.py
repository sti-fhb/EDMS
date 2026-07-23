"""啟用帳號共用副作用（US2 驗證 / US4 邀請啟用共用，#67）。

「建 DP_USER(ACTIVE) + 首筆 PWD_HIST + 授 ET 學員 + 雙稽核 + 刪待驗證列」為 US2 verify（#56）與
US4 activate（#67）共同的啟用副作用，唯一差異是**密碼來源**（US2 用 pending.pwd_hash＝註冊時所填、
US4 用使用者於邀請連結當場設定）。抽為共用函式，避免兩處實作漂移（#56 交接備忘所提原則）。
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.dp.user.ids import generate_user_id
from app.dp.user.models import DpPendingRegistration
from app.dp.user.repository import AuthRepository
from app.services import AuditLogService

_ET_MODULE = "ET"
_ALREADY_MSG = "此 Email 已被註冊，請直接登入或使用忘記密碼"


async def activate_pending_account(
    db: AsyncSession,
    *,
    pending: DpPendingRegistration,
    pwd_hash: str,
    now: datetime,
    ip: str | None,
    repo: AuthRepository,
    audit: AuditLogService,
    func_name: str,
    create_desc: str,
) -> str:
    """啟用待驗證 / 待邀請帳號並回傳新 USER_ID。

    建 `DP_USER`(ACTIVE) + 首筆 `PWD_HIST` + 授 ET 學員 + 雙稽核 + 刪 pending 列。
    冪等性以 `UQ_DP_USER_EMAIL` 為底層保證：重複 / 競態啟用 → 第一個建成、其餘乾淨拒絕（409）。

    Args:
        pending: 待驗證 / 待邀請列
        pwd_hash: 密碼雜湊（US2＝pending.pwd_hash；US4＝使用者當場設定並雜湊）
        func_name: 稽核 func_name（US2「DP-REGISTER」/ US4「DP-USERS」）
        create_desc: 建帳號稽核描述

    Returns:
        新建 `DP_USER` 之 USER_ID

    Raises:
        AppError: Email 已完成啟用 / 競態（409 DP_USER_001）
    """
    user_id = generate_user_id()
    try:
        # 撞 UQ_DP_USER_EMAIL 代表已被啟用 / 競態，冪等拒絕
        await repo.create_user(
            db,
            user_id=user_id,
            email=pending.email,
            user_name=pending.user_name,
            pwd_hash=pwd_hash,
            operator_id=user_id,
            now=now,
        )
    except IntegrityError as exc:
        raise AppError(status_code=409, detail=_ALREADY_MSG, error_code="DP_USER_001") from exc

    await repo.add_pwd_history(db, user_id=user_id, seq_no=1, pwd_hash=pwd_hash, operator_id=user_id, now=now)
    await module_provisioning_gate.grant_default_role(_ET_MODULE, user_id, db)
    await _audit(db, audit, func_name=func_name, user_id=user_id, ip=ip, desc=create_desc)
    await _audit(db, audit, func_name=func_name, user_id=user_id, ip=ip, desc="授予預設 ET 學員角色")
    await repo.delete_pending_by_token_hash(db, pending.token_hash)
    return user_id


async def _audit(
    db: AsyncSession, audit: AuditLogService, *, func_name: str, user_id: str, ip: str | None, desc: str
) -> None:
    await audit.log_action(
        db,
        module="DP",
        func_name=func_name,
        action_type="CREATE",
        result="SUCCESS",
        operator_id=user_id,
        target_id=user_id,
        description=desc,
        source_ip=ip,
    )
