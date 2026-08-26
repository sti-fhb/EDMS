"""啟用帳號的共用流程與副作用（US2 驗證 / US4 邀請啟用共用）。

「建 DP_USER(ACTIVE) + 首筆 PWD_HIST + 授 ET 學員 + 雙稽核 + 刪待驗證列」是兩條流程共同的
啟用副作用（#67 抽出）。

2026-08-25（#212）起，兩條流程的**密碼來源也統一**了：US2 原本用 pending.pwd_hash（註冊當下
所填），而那正是 pre-hijack 的根源——任何人可用他人 Email 註冊並填自己的密碼，受害者點下
（來自組織網域、格式正確的）驗證信後，帳號就以攻擊者的密碼建立。改為與 US4 一致：pending 列
不存密碼，密碼由**點連結者當場設定**。因此 `activate_with_new_password` 也抽為共用，兩條流程
只剩「預期的 KIND」「使用者訊息文案」「稽核 FUNC_NAME」三處差異。
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_provisioning import module_provisioning_gate
from app.core.password_hashing import hash_password_async
from app.core.password_policy import validate_password_strength
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.user.ids import generate_user_id
from app.dp.user.models import DpPendingRegistration
from app.dp.user.repository import AuthRepository
from app.dp.user.token import hash_token
from app.services import AuditLogService, ParamService

_ET_MODULE = "ET"
_DEFAULT_MIN_LEN = 8
_DEFAULT_CHAR_TYPES = 3
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
        pwd_hash: 密碼雜湊。**US2 / US4 皆為使用者於本步當場設定並雜湊**——#212 之後
            待驗證列不存密碼，`pending.pwd_hash` 恆為 None，該來源已不存在
        func_name: 稽核 func_name（US2「DP-REGISTER」/ US4「DP-USERS」）
        create_desc: 建帳號稽核描述

    Returns:
        新建 `DP_USER` 之 USER_ID

    Raises:
        AppError: Email 已完成啟用 / 競態（409 DP_USER_001）
    """
    # 刻意重新產生，**不沿用** pending.invite_id（US4 管理者邀請時配發之邀請識別碼）：
    # 邀請可能永遠不會啟用（Email 打錯、逾時未點連結），沿用會讓未啟用帳號的 ID 提前
    # 佔用正式帳號的號碼空間，違反 #56 方案 B「驗證通過前不寫 DP_USER、DP_USER 只存已
    # 驗證帳號」之設計。邀請與帳號為兩個不同實體、識別碼分開存放，兩者以 Email 關聯。
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
    # 以 Email（而非 token_hash）刪 pending：若啟用與管理者重寄競態、pending 列已被換成新 token，
    # 以 token_hash 刪會 no-op 而殘留一筆已無意義的邀請列；以 Email 刪可清掉該 Email 之任何 pending 列。
    await repo.delete_pending_by_email(db, pending.email)
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


async def activate_with_new_password(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
    confirm_password: str,
    expected_kind: str,
    repo: AuthRepository,
    audit: AuditLogService,
    params: ParamService,
    func_name: str,
    create_desc: str,
    token_invalid_msg: str,
    token_expired_msg: str,
) -> str:
    """驗 token → 檢核並設定密碼 → 啟用帳號，回傳新 USER_ID。

    US2（自助註冊驗證）與 US4（邀請啟用）共用；差異僅在 `expected_kind`、使用者訊息文案與
    稽核 `func_name`。密碼一律由**點連結者當場設定**，pending 列不存任何密碼素材（#212）。

    Args:
        expected_kind: 本端點接受的 KIND；不符者一律視為 token 無效（自助註冊 token 不得走
            邀請端點，反之亦然），明確檢查而非靠 DB 約束兜底。
        token_invalid_msg / token_expired_msg: 兩條流程的使用者文案不同（「驗證連結」vs
            「邀請連結」），故由呼叫方傳入。

    Raises:
        AppError: token 無效 / KIND 不符（400 DP_USER_003）、逾期（400 DP_USER_004）、
            兩次不一致（422 DP_USER_002）、密碼不符複雜度（422 DP_PWD_001/002/004）、
            Email 已啟用 / 競態（409 DP_USER_001）。
    """
    now = utcnow()
    pending = await repo.get_pending_by_token_hash(db, hash_token(token))
    if pending is None or pending.kind != expected_kind:
        raise AppError(status_code=400, detail=token_invalid_msg, error_code="DP_USER_003")
    if pending.expires_date <= now:
        raise AppError(status_code=400, detail=token_expired_msg, error_code="DP_USER_004")

    # 密碼檢核：兩次一致（前端 Zod 另擋）+ 複雜度（一般使用者門檻，讀平台參數）
    if new_password != confirm_password:
        raise AppError(status_code=422, detail="兩次輸入之密碼不一致", error_code="DP_USER_002")
    min_len = await params.get_int_param(db, "PWD_POLICY", "MIN_LEN", _DEFAULT_MIN_LEN)
    char_types = await params.get_int_param(db, "PWD_POLICY", "CHAR_TYPES", _DEFAULT_CHAR_TYPES)
    validate_password_strength(new_password, min_length=min_len, required_char_types=char_types)

    return await activate_pending_account(
        db,
        pending=pending,
        pwd_hash=await hash_password_async(new_password),
        now=now,
        ip=get_client_ip(),
        repo=repo,
        audit=audit,
        func_name=func_name,
        create_desc=create_desc,
    )
