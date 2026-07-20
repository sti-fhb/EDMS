from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.user.models import DpPwdHistory
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
