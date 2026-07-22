from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.users.models import DpUser


class UsersRepository:
    """使用者管理（US4）DP_USER 存取：查詢 / 狀態 / 解鎖 / 基本資料。

    帳號建立（含授學員 / 首筆歷程）重用 `app.dp.user.AuthRepository`，本 repository 不重複實作。
    """

    def build_list_stmt(self, *, keyword: str | None, status: str | None, now: datetime) -> Select:
        """組清單查詢 Select（不含 offset/limit，交 paginate）。

        keyword：對姓名 / Email 做不分大小寫模糊比對。
        status：active（啟用中且未鎖定）/ disabled（已停用）/ locked（啟用中但鎖定未逾時）；None＝全部。
        """
        conditions = [DpUser.deleted == 0]

        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(or_(DpUser.user_name.ilike(pattern), DpUser.email.ilike(pattern)))

        if status == "active":
            conditions.append(DpUser.status == "ACTIVE")
            conditions.append(or_(DpUser.locked_until.is_(None), DpUser.locked_until <= now))
        elif status == "disabled":
            conditions.append(DpUser.status == "DISABLED")
        elif status == "locked":
            conditions.append(and_(DpUser.status == "ACTIVE", DpUser.locked_until.is_not(None), DpUser.locked_until > now))

        return select(DpUser).where(*conditions).order_by(DpUser.created_date.desc(), DpUser.user_id)

    async def get_by_id(self, db: AsyncSession, user_id: str) -> DpUser | None:
        """以 USER_ID 查使用者（排除軟刪除）；不存在回 None。"""
        stmt = select(DpUser).where(DpUser.user_id == user_id, DpUser.deleted == 0)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def email_taken(self, db: AsyncSession, email: str, *, exclude_user_id: str | None = None) -> bool:
        """該 Email 是否已被其他帳號使用（含軟刪除，對齊 EMAIL UNIQUE）；exclude 用於編輯時排除自己。"""
        stmt = select(func.count()).select_from(DpUser).where(DpUser.email == email)
        if exclude_user_id is not None:
            stmt = stmt.where(DpUser.user_id != exclude_user_id)
        return (await db.execute(stmt)).scalar_one() > 0

    async def set_status(self, db: AsyncSession, *, user: DpUser, status: str, operator_id: str, now: datetime) -> None:
        """更新帳號狀態（ACTIVE / DISABLED）+ 稽核欄位並 flush。"""
        user.status = status
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    async def unlock(self, db: AsyncSession, *, user: DpUser, operator_id: str, now: datetime) -> None:
        """解鎖：登入失敗計數歸零 + 清鎖定截止 + 稽核欄位並 flush。"""
        user.login_fail_count = 0
        user.locked_until = None
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    async def update_basic(
        self, db: AsyncSession, *, user: DpUser, user_name: str, email: str, operator_id: str, now: datetime
    ) -> None:
        """更新姓名 / Email（直接生效）+ 稽核欄位並 flush。"""
        user.user_name = user_name
        user.email = email
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()
