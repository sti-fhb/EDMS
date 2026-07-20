from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.users.models import DpUser


class AuthRepository:
    """認證相關 DP_USER 存取（登入 / 換發 / 登出）。"""

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
