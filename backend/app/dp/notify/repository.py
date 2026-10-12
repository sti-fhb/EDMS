from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.notify.models import DpEmailLog, DpNotifyTemplate


class NotifyRepository:
    """通知範本查詢 + 寄件 outbox 存取（DP_NOTIFY_TEMPLATE / DP_EMAIL_LOG）。"""

    async def get_template(self, db: AsyncSession, module: str, template_code: str) -> DpNotifyTemplate | None:
        """取範本；不存在回 None（軟刪除項排除）。"""
        stmt = select(DpNotifyTemplate).where(
            DpNotifyTemplate.module == module,
            DpNotifyTemplate.template_code == template_code,
            DpNotifyTemplate.deleted == 0,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_templates(
        self, db: AsyncSession, modules: list[str], *, channels: tuple[str, ...] | None = None
    ) -> list[DpNotifyTemplate]:
        """列指定 MODULE 之範本（US9 維護頁；依 MODULE / TEMPLATE_CODE 排序、排除軟刪除）。

        `channels` 非 None 時再以 CHANNEL 過濾（#554：DP04 只維護會寄 Email 的範本）。
        """
        stmt = select(DpNotifyTemplate).where(DpNotifyTemplate.module.in_(modules), DpNotifyTemplate.deleted == 0)
        if channels is not None:
            stmt = stmt.where(DpNotifyTemplate.channel.in_(channels))
        stmt = stmt.order_by(DpNotifyTemplate.module, DpNotifyTemplate.template_code)
        return list((await db.execute(stmt)).scalars().all())

    async def update_template_versioned(
        self,
        db: AsyncSession,
        *,
        module: str,
        template_code: str,
        version: int,
        fields: dict,
        operator_id: str,
        now: datetime,
    ) -> int | None:
        """樂觀鎖更新範本：僅當 DB `VERSION` 等於傳入 version 才成功、同時 `VERSION+1`（US9 FR-05）。

        以單一條件式 `UPDATE ... WHERE VERSION=:v ... RETURNING VERSION` 關閉「查→改」TOCTOU——
        並發儲存同範本時只有一個成功（拿到新版本號），其餘比對 0 列回 None（＝版本衝突）。
        回傳更新後的新 VERSION；比對 0 列（版本落後 / 範本不存在）回 None。
        """
        stmt = (
            update(DpNotifyTemplate)
            .where(
                DpNotifyTemplate.module == module,
                DpNotifyTemplate.template_code == template_code,
                DpNotifyTemplate.version == version,
                DpNotifyTemplate.deleted == 0,
            )
            .values(**fields, version=version + 1, updated_user=operator_id, updated_date=now)
            .returning(DpNotifyTemplate.version)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def add_logs(self, db: AsyncSession, rows: list[dict]) -> None:
        """新增多列 outbox；**整批只 flush 一次**（commit 由呼叫方交易負責）。

        #563 前為逐列 `add()` + `flush()`，於是 N 位收件人就是 N 次 round-trip。當時單次
        呼叫最多 50 人（`MAX_RECIPIENTS` 超過即拋），所以上界是固定的；DM 改為分批之後 N
        由機構內閱覽者人數決定，而這整段跑在核准交易裡、且該交易已持有 review 列的
        `FOR UPDATE` 鎖——逐列 flush 會讓鎖持有時間隨人口線性成長。

        批尾單次 flush 讓 SQLAlchemy 合併成 executemany，round-trip 降到每批一次。語意不變：
        仍只 flush 不 commit，失敗仍由呼叫方交易 rollback。
        """
        if not rows:
            return
        db.add_all([DpEmailLog(**values) for values in rows])
        await db.flush()

    async def list_pending_for_attempt(
        self, db: AsyncSession, *, limit: int, interval_minutes: int, now: datetime
    ) -> list[DpEmailLog]:
        """取可嘗試寄送的 PENDING 信件（用 (STATUS, CREATED_DATE) 索引，依建立序）。

        重試間隔：從未嘗試（UPDATED_DATE 為 NULL）或距上次嘗試已逾 interval_minutes 者才撿起，
        避免對剛失敗的信件過於頻繁重試。
        """
        cutoff = now - timedelta(minutes=interval_minutes)
        stmt = (
            select(DpEmailLog)
            .where(
                DpEmailLog.status == "PENDING",
                or_(DpEmailLog.updated_date.is_(None), DpEmailLog.updated_date <= cutoff),
            )
            .order_by(DpEmailLog.created_date, DpEmailLog.message_id)
            .limit(limit)
            # FOR UPDATE SKIP LOCKED：鎖住撿起的列直到本輪 commit，多實例 worker 併發時
            # 各自跳過對方鎖定的列，避免同一封信被重複寄送（canonical outbox 消費模式）。
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
