from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.audit.models import DpAuditLog

# 固定 advisory lock key：序列化稽核鏈接的「讀前列 → 插入」臨界區，避免並行 append 讀到同一
# prev ROW_HASH 造成鏈分岔。xact 級鎖，隨交易結束自動釋放。
_AUDIT_CHAIN_LOCK_KEY = 4823011


class AuditLogRepository:
    """DP_AUDIT_LOG 資料存取（append-only）。

    刻意**不提供** update / delete 方法：append-only 於應用層落地（research §6）；
    DB 帳號僅 GRANT INSERT / SELECT 屬部署層（見 issue #22）。
    """

    async def acquire_chain_lock(self, db: AsyncSession) -> None:
        """取得鏈接臨界區的 xact advisory lock，序列化並行的稽核寫入。

        設計取捨：pg_advisory_xact_lock 為**交易層級**鎖，持有至呼叫方**整個外層交易**
        commit / rollback 才釋放（非僅「讀前列→插入」窄臨界區）。因會呼叫稽核的情境
        （登入登出、帳號 / 角色權限異動）頻率不高，可接受；若未來高頻呼叫需縮小臨界區，
        再評估改用巢狀交易 / savepoint。
        並行不分岔之正確性以 advisory lock 語意 + code review 保證，未做並發實測
        （現行 per-test rollback fixture 難以模擬多 committed 交易並發）。
        """
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_AUDIT_CHAIN_LOCK_KEY))

    async def get_last_row_hash(self, db: AsyncSession) -> str | None:
        """取最新一列的 ROW_HASH；無資料（genesis）回 None。"""
        result = await db.execute(select(DpAuditLog.row_hash).order_by(DpAuditLog.log_id.desc()).limit(1))
        return result.scalar_one_or_none()

    async def insert(self, db: AsyncSession, values: dict) -> None:
        """新增一列稽核；只 flush（commit 由呼叫方交易負責）。"""
        db.add(DpAuditLog(**values))
        await db.flush()
