from datetime import datetime

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.user.models import DpPendingRegistration, DpPwdHistory, DpPwdReset
from app.dp.users.models import DpUser

_SYSTEM_USER = "SYSTEM"
_KIND_SELF_REGISTER = "SELF_REGISTER"
_KIND_ADMIN_INVITE = "ADMIN_INVITE"
_TOKEN_TYPE_EMAIL_CHANGE = "EMAIL_CHANGE"  # noqa: S105 — DP_PWD_RESET.TOKEN_TYPE 值，非密碼


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

    async def email_taken_for_change(self, db: AsyncSession, email: str, *, requester_id: str) -> bool:
        """Email 變更之目標唯一性：已被任一帳號使用（EMAIL）或**他人**待驗證中（PENDING_EMAIL）即為已占用。

        延遲切換下 `email_exists` 只查 EMAIL 會漏「他人已申請改為同一新信箱、尚未驗證」的窗口
        （US8 code review）；故一併查他人 PENDING_EMAIL（排除自己，允許本人重複申請同一新信箱）。
        """
        stmt = select(func.count()).select_from(DpUser).where(
            (DpUser.email == email) | ((DpUser.pending_email == email) & (DpUser.user_id != requester_id))
        )
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
        must_change_pwd: bool = False,
    ) -> DpUser:
        """建立啟用中（ACTIVE）使用者並 flush；PWD_CHANGED_DATE 設為建立當下。

        must_change_pwd 預設 False（US2 自助註冊者自設密碼）；US4 管理者代建初始密碼時傳 True
        （首次登入強制變更，spec.md 釐清第 1 輪 / FR-DP-US4-03）。
        """
        user = DpUser(
            user_id=user_id,
            email=email,
            pwd_hash=pwd_hash,
            user_name=user_name,
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=must_change_pwd,
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

    async def update_name(
        self, db: AsyncSession, *, user: DpUser, user_name: str, operator_id: str, now: datetime
    ) -> None:
        """更新使用者姓名（US8 個資維護，直接生效、ET / DM 共用同表）。"""
        user.user_name = user_name
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    async def set_pending_email(
        self, db: AsyncSession, *, user: DpUser, pending_email: str, operator_id: str, now: datetime
    ) -> None:
        """設定待驗證新信箱（US8 Email 變更申請，尚未生效；供前端顯示與防同時多筆）。"""
        user.pending_email = pending_email
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    async def switch_email(
        self, db: AsyncSession, *, user: DpUser, new_email: str, operator_id: str, now: datetime
    ) -> None:
        """切換登入 Email 為新值並清 PENDING_EMAIL（US8 Email 變更驗證通過，延遲生效落地）。"""
        user.email = new_email
        user.pending_email = None
        user.updated_user = operator_id
        user.updated_date = now
        await db.flush()

    # --- 待驗證註冊（DP_PENDING_REGISTRATION，#56 方案 B）---

    async def get_pending_by_email(self, db: AsyncSession, email: str) -> DpPendingRegistration | None:
        """以 Email 查待驗證註冊；不存在回 None（供登入未驗證提示、重寄）。"""
        stmt = select(DpPendingRegistration).where(DpPendingRegistration.email == email)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_pending_by_token_hash(self, db: AsyncSession, token_hash: str) -> DpPendingRegistration | None:
        """以 token 之 SHA-256 查待驗證註冊；效期判定由服務層負責。不存在回 None。"""
        stmt = select(DpPendingRegistration).where(DpPendingRegistration.token_hash == token_hash)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def delete_pending_by_email(self, db: AsyncSession, email: str) -> None:
        """刪除某 Email 的待驗證註冊（重新註冊 / 重寄前先清舊列，維持 EMAIL 唯一）。"""
        await db.execute(delete(DpPendingRegistration).where(DpPendingRegistration.email == email))

    async def delete_pending_by_token_hash(self, db: AsyncSession, token_hash: str) -> None:
        """驗證通過後刪除該待驗證註冊列（已消費）。"""
        await db.execute(delete(DpPendingRegistration).where(DpPendingRegistration.token_hash == token_hash))

    async def create_pending_registration(
        self,
        db: AsyncSession,
        *,
        token_hash: str,
        email: str,
        user_name: str,
        pwd_hash: str | None,
        expires_date: datetime,
        now: datetime,
        kind: str = _KIND_SELF_REGISTER,
        res_id: str | None = None,
        operator_id: str = _SYSTEM_USER,
    ) -> None:
        """新增一筆待驗證 / 待啟用列（token 僅存 SHA-256）；呼叫方須先清同 Email 舊列。

        kind＝SELF_REGISTER（US2 自助註冊，建立即帶 pwd_hash）或 ADMIN_INVITE（US4 邀請，
        pwd_hash 為 None、res_id 作為對外識別碼、operator_id 為管理者）。
        """
        db.add(
            DpPendingRegistration(
                token_hash=token_hash,
                email=email,
                user_name=user_name,
                pwd_hash=pwd_hash,
                kind=kind,
                res_id=res_id,
                expires_date=expires_date,
                created_user=operator_id,
                created_date=now,
            )
        )
        await db.flush()

    # --- 管理者邀請（ADMIN_INVITE）專用查詢（US4 #67）---

    def build_invite_list_stmt(self, *, keyword: str | None) -> Select:
        """組「待啟用邀請」清單 Select（僅 ADMIN_INVITE，不含 offset/limit，交 paginate）。

        keyword：對姓名 / Email 不分大小寫模糊比對。依邀請寄出時間新到舊排序。
        """
        conditions = [DpPendingRegistration.kind == _KIND_ADMIN_INVITE]
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                func.lower(DpPendingRegistration.user_name).like(func.lower(pattern))
                | func.lower(DpPendingRegistration.email).like(func.lower(pattern))
            )
        return (
            select(DpPendingRegistration)
            .where(*conditions)
            .order_by(DpPendingRegistration.created_date.desc(), DpPendingRegistration.email)
        )

    async def get_invite_by_res_id(self, db: AsyncSession, res_id: str) -> DpPendingRegistration | None:
        """以 RES_ID 查邀請中列（僅 ADMIN_INVITE）；不存在回 None。"""
        stmt = select(DpPendingRegistration).where(
            DpPendingRegistration.res_id == res_id,
            DpPendingRegistration.kind == _KIND_ADMIN_INVITE,
        )
        return (await db.execute(stmt)).scalar_one_or_none()

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
        new_email: str | None = None,
    ) -> None:
        """新增一次性重設 token（僅存 SHA-256）。

        new_email 僅 EMAIL_CHANGE 型帶值（待驗證之新信箱，驗證通過才切換 DP_USER.EMAIL）。
        """
        db.add(
            DpPwdReset(
                token_hash=token_hash,
                user_id=user_id,
                token_type=token_type,
                new_email=new_email,
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

    async def consume_reset_token(
        self, db: AsyncSession, *, token_hash: str, token_type: str, now: datetime
    ) -> str | None:
        """原子作廢並取回 token 對應 USER_ID：僅當「未使用且未逾時」才成功（RETURNING）。

        以單一條件式 UPDATE 關閉「查詢未使用 → 標記已用」之間的 TOCTOU 空窗——並發提交同一 token 時，
        只有第一個請求會更新到列（拿到 user_id），其餘回 None，確保一次性 token 不變量在並發下成立。
        回 None 代表 token 不存在 / 已用 / 已逾時（呼叫方一律轉 DP_PWD_005）。
        """
        stmt = (
            update(DpPwdReset)
            .where(
                DpPwdReset.token_hash == token_hash,
                DpPwdReset.token_type == token_type,
                DpPwdReset.used_date.is_(None),
                DpPwdReset.expires_date > now,
            )
            .values(used_date=now)
            .returning(DpPwdReset.user_id)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def consume_email_change_token(
        self, db: AsyncSession, *, token_hash: str, now: datetime
    ) -> tuple[str, str] | None:
        """原子作廢 EMAIL_CHANGE token 並取回 (USER_ID, NEW_EMAIL)：僅當「未使用且未逾時」才成功。

        同 consume_reset_token 以單一條件式 UPDATE 關閉 TOCTOU；並發同 token 只有一個成功。
        回 None 代表 token 不存在 / 已用 / 已逾時（呼叫方轉 DP_PWD_005）。NEW_EMAIL 理論上非空
        （EMAIL_CHANGE 建立時必帶），為型別安全仍防呆：缺值視同無效 token。
        """
        stmt = (
            update(DpPwdReset)
            .where(
                DpPwdReset.token_hash == token_hash,
                DpPwdReset.token_type == _TOKEN_TYPE_EMAIL_CHANGE,
                DpPwdReset.used_date.is_(None),
                DpPwdReset.expires_date > now,
            )
            .values(used_date=now)
            .returning(DpPwdReset.user_id, DpPwdReset.new_email)
        )
        row = (await db.execute(stmt)).first()
        if row is None or row.new_email is None:
            return None
        return (row.user_id, row.new_email)
