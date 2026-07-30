from datetime import date, datetime, timedelta, timezone

from sqlalchemy import ColumnElement, Row, Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.audit.models import DpAuditLog
from app.dp.users.models import DpUser

# 固定 advisory lock key：序列化稽核鏈接的「讀前列 → 插入」臨界區，避免並行 append 讀到同一
# prev ROW_HASH 造成鏈分岔。xact 級鎖，隨交易結束自動釋放。
_AUDIT_CHAIN_LOCK_KEY = 4823011


def build_audit_conditions(
    *,
    operator: str | None,
    module: str | None,
    action_type: str | None,
    result: str | None,
    date_from: date | None,
    date_to: date | None,
) -> list[ColumnElement[bool]]:
    """組稽核查詢的 WHERE 條件（唯讀，皆為選填 AND 疊加）。

    operator：對 操作者 USER_ID / 姓名 / Email 不分大小寫模糊比對——`created_user` 直接 ilike
    （相容 SYSTEM 與已不存在之 USER_ID），並 OR 上「姓名 / Email 命中之 USER_ID 子查詢」。
    date_to：以「< 隔日 00:00 UTC」表達含當日全天（`created_date` 為 timezone-aware UTC）。
    """
    conditions: list[ColumnElement[bool]] = []

    if operator:
        pattern = f"%{operator}%"
        matching_users = select(DpUser.user_id).where(
            or_(
                DpUser.user_id.ilike(pattern),
                DpUser.user_name.ilike(pattern),
                DpUser.email.ilike(pattern),
            )
        )
        conditions.append(or_(DpAuditLog.created_user.ilike(pattern), DpAuditLog.created_user.in_(matching_users)))
    if module:
        conditions.append(DpAuditLog.module == module)
    if action_type:
        conditions.append(DpAuditLog.action_type == action_type)
    if result:
        conditions.append(DpAuditLog.result == result)
    if date_from:
        conditions.append(
            DpAuditLog.created_date >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
        )
    if date_to:
        upper = datetime(date_to.year, date_to.month, date_to.day, tzinfo=timezone.utc) + timedelta(days=1)
        conditions.append(DpAuditLog.created_date < upper)

    return conditions


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

    # ── 查詢 / 匯出（US10，唯讀）────────────────────────────────────────────

    @staticmethod
    def _select_with_operator(conditions: list[ColumnElement[bool]]) -> Select:
        """組「稽核 + 操作者姓名 / email」查詢：LEFT JOIN DP_USER，時間倒序。

        LEFT JOIN 不濾 DP_USER.deleted：操作者事後被軟刪除時仍呈現當時姓名（歷史留痕）。
        """
        return (
            select(
                DpAuditLog,
                DpUser.user_name.label("operator_name"),
                DpUser.email.label("operator_email"),
            )
            .outerjoin(DpUser, DpAuditLog.created_user == DpUser.user_id)
            .where(*conditions)
            .order_by(DpAuditLog.created_date.desc(), DpAuditLog.log_id.desc())
        )

    async def count_logs(self, db: AsyncSession, *, conditions: list[ColumnElement[bool]]) -> int:
        """符合條件之總筆數（供手動分頁 meta）。"""
        count_stmt = select(func.count()).select_from(select(DpAuditLog.log_id).where(*conditions).subquery())
        raw = await db.scalar(count_stmt)
        return raw if raw is not None else 0

    async def list_logs(
        self, db: AsyncSession, *, conditions: list[ColumnElement[bool]], offset: int, limit: int
    ) -> list[Row]:
        """取一頁稽核（含 operator_name），時間倒序。"""
        stmt = self._select_with_operator(conditions).offset(offset).limit(limit)
        return list((await db.execute(stmt)).all())

    async def fetch_for_export(self, db: AsyncSession, *, conditions: list[ColumnElement[bool]]) -> list[Row]:
        """依條件取全量稽核（含 operator_name），供 CSV 匯出（無分頁）。"""
        stmt = self._select_with_operator(conditions)
        return list((await db.execute(stmt)).all())
