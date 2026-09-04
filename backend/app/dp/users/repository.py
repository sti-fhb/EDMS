from collections.abc import Collection
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.users.account_status import account_usable_clause
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
            # 與 #250 之 is_account_usable / DM 指定審核者下拉共用同一條件，避免多份判定漂移
            conditions.append(account_usable_clause(now))
        elif status == "disabled":
            conditions.append(DpUser.status == "DISABLED")
        elif status == "locked":
            conditions.append(
                and_(DpUser.status == "ACTIVE", DpUser.locked_until.is_not(None), DpUser.locked_until > now)
            )

        return select(DpUser).where(*conditions).order_by(DpUser.created_date.desc(), DpUser.user_id)

    async def get_by_id(self, db: AsyncSession, user_id: str) -> DpUser | None:
        """以 USER_ID 查使用者（排除軟刪除）；不存在回 None。"""
        stmt = select(DpUser).where(DpUser.user_id == user_id, DpUser.deleted == 0)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def fetch_display_names(self, db: AsyncSession, user_ids: Collection[str]) -> dict[str, str]:
        """批次取 USER_ID → 顯示名（姓名，無姓名時退 email）；查無者不放入。供「最後異動者」顯示。"""
        if not user_ids:
            return {}
        rows = (
            await db.execute(select(DpUser.user_id, DpUser.user_name, DpUser.email).where(DpUser.user_id.in_(user_ids)))
        ).all()
        return {uid: (name or email) for uid, name, email in rows}

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

    async def update_name(
        self, db: AsyncSession, *, user: DpUser, user_name: str, operator_id: str, now: datetime
    ) -> None:
        """更新姓名（#67：Email 為登入帳號、唯讀不可代改）+ 稽核欄位並 flush。"""
        user.user_name = user_name
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    # ── 平台每日排程 SCHDP001（US11）用之查詢 ─────────────────────────────

    async def find_idle_active(self, db: AsyncSession, *, idle_before: datetime) -> list[DpUser]:
        """閒置逾期之啟用帳號：`ACTIVE` 且 `COALESCE(LAST_LOGIN_DATE, CREATED_DATE) < idle_before`。

        從未登入（LAST_LOGIN_DATE 為 null）者以 CREATED_DATE 為閒置起算基準（spec_us11 FR-05）。
        """
        stmt = select(DpUser).where(
            DpUser.deleted == 0,
            DpUser.status == "ACTIVE",
            func.coalesce(DpUser.last_login_date, DpUser.created_date) < idle_before,
        )
        return list((await db.execute(stmt)).scalars().all())

    async def find_pwd_expiring(
        self, db: AsyncSession, *, not_expired_after: datetime, remind_on_or_before: datetime
    ) -> list[DpUser]:
        """密碼即將到期（尚未到期、且落在提醒窗）之啟用帳號。

        到期日＝`PWD_CHANGED_DATE + EXPIRY_DAYS`；提醒窗＝到期前 `EXPIRY_REMIND_DAYS` 天內。
        以 `PWD_CHANGED_DATE >= not_expired_after`（尚未到期）AND `<= remind_on_or_before`（已進窗）表達。
        """
        stmt = select(DpUser).where(
            DpUser.deleted == 0,
            DpUser.status == "ACTIVE",
            DpUser.pwd_changed_date >= not_expired_after,
            DpUser.pwd_changed_date <= remind_on_or_before,
        )
        return list((await db.execute(stmt)).scalars().all())
