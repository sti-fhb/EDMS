from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.user.models import DpPwdHistory, DpPwdReset
from app.dp.users.models import DpUser


class AuthRepository:
    """認證相關 DP_USER 存取（登入 / 換發 / 登出 / 註冊）。"""

    async def get_by_email(self, db: AsyncSession, email: str) -> DpUser | None:
        """以 Email 查使用者（排除軟刪除）；不存在回 None。"""
        stmt = select(DpUser).where(DpUser.email == email, DpUser.deleted == 0)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id(self, db: AsyncSession, user_id: str) -> DpUser | None:
        """以 USER_ID 查使用者（排除軟刪除）；不存在回 None。"""
        stmt = select(DpUser).where(DpUser.user_id == user_id, DpUser.deleted == 0)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, db: AsyncSession, email: str) -> bool:
        """該 Email 是否已被註冊（含軟刪除，避免與既有帳號 EMAIL UNIQUE 衝突）。"""
        stmt = select(func.count()).select_from(DpUser).where(DpUser.email == email)
        return (await db.execute(stmt)).scalar_one() > 0

    async def create_user(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        email: str,
        user_name: str,
        pwd_hash: str,
        operator_id: str,
        now: datetime,
    ) -> DpUser:
        """建立啟用中（ACTIVE）使用者並 flush；PWD_CHANGED_DATE 設為建立當下。"""
        user = DpUser(
            user_id=user_id,
            email=email,
            pwd_hash=pwd_hash,
            user_name=user_name,
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user=operator_id,
            created_date=now,
        )
        db.add(user)
        await db.flush()
        return user

    async def add_pwd_history(
        self, db: AsyncSession, *, user_id: str, seq_no: int, pwd_hash: str, operator_id: str, now: datetime
    ) -> None:
        """新增一筆密碼歷程（append-only）；SEQ_NO 由呼叫方指派。"""
        db.add(
            DpPwdHistory(
                user_id=user_id,
                seq_no=seq_no,
                pwd_hash=pwd_hash,
                created_user=operator_id,
                created_date=now,
            )
        )
        await db.flush()

    async def next_pwd_seq_no(self, db: AsyncSession, user_id: str) -> int:
        """該使用者密碼歷程的下一個 SEQ_NO（現有最大 +1；無歷程回 1）。"""
        stmt = select(func.max(DpPwdHistory.seq_no)).where(DpPwdHistory.user_id == user_id)
        return ((await db.execute(stmt)).scalar_one() or 0) + 1

    async def recent_pwd_hashes(self, db: AsyncSession, user_id: str, limit: int) -> list[str]:
        """取該使用者最近 limit 筆密碼雜湊（SEQ_NO 由大到小），供重複性檢核。"""
        stmt = (
            select(DpPwdHistory.pwd_hash)
            .where(DpPwdHistory.user_id == user_id)
            .order_by(DpPwdHistory.seq_no.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def update_password(
        self, db: AsyncSession, *, user: DpUser, pwd_hash: str, operator_id: str, now: datetime
    ) -> None:
        """更新使用者密碼與變更時間；清 MUST_CHANGE_PWD（使用者已自設密碼）。**不動鎖定 / 停用狀態**。"""
        user.pwd_hash = pwd_hash
        user.pwd_changed_date = now
        user.must_change_pwd = False
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    # --- 密碼重設 token（DP_PWD_RESET）---

    async def invalidate_active_reset_tokens(
        self, db: AsyncSession, *, user_id: str, token_type: str, now: datetime
    ) -> None:
        """作廢同使用者同型別所有未使用的 token（一次性：新申請前先廢舊）。"""
        stmt = (
            update(DpPwdReset)
            .where(
                DpPwdReset.user_id == user_id,
                DpPwdReset.token_type == token_type,
                DpPwdReset.used_date.is_(None),
            )
            .values(used_date=now)
        )
        await db.execute(stmt)

    async def create_reset_token(
        self,
        db: AsyncSession,
        *,
        token_hash: str,
        user_id: str,
        token_type: str,
        expires_date: datetime,
        operator_id: str,
        now: datetime,
    ) -> None:
        """新增一次性重設 token（僅存 SHA-256）。"""
        db.add(
            DpPwdReset(
                token_hash=token_hash,
                user_id=user_id,
                token_type=token_type,
                expires_date=expires_date,
                created_user=operator_id,
                created_date=now,
            )
        )
        await db.flush()

    async def get_reset_token_by_hash(self, db: AsyncSession, token_hash: str, token_type: str) -> DpPwdReset | None:
        """以 SHA-256 查 token 列（不論是否逾時 / 已用，效期與使用狀態由服務層判定）；不存在回 None。"""
        stmt = select(DpPwdReset).where(DpPwdReset.token_hash == token_hash, DpPwdReset.token_type == token_type)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def mark_reset_token_used(self, db: AsyncSession, *, token: DpPwdReset, now: datetime) -> None:
        """標記 token 已使用（作廢）。"""
        token.used_date = now
        await db.flush()
