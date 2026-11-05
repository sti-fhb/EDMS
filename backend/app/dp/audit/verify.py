"""稽核 ROW_HASH 鏈驗證工具（T052，唯讀）。

依 `LOG_ID` 遞增（＝建鏈序，見 service.get_last_row_hash 取 desc limit 1）分批走訪
`DP_AUDIT_LOG` 全表，逐列重算鏈式雜湊並與存檔 `ROW_HASH` 比對；`prev` 以「前一列的
**存檔** ROW_HASH」接鏈——任一列遭竄改（含攻擊者一併改該列自身 hash 但無法連改後續）
都會在該列或下一列現形。回報最早（`LOG_ID` 最小）的斷鏈位置。

重用 service._compute_row_hash（同一 canonical hash 定義），避免驗證端與寫入端漂移。

ops 例行稽核 / CI 可直接執行：
    python -m app.dp.audit.verify
退出碼：0＝完好（OK / 空表 EMPTY）、1＝斷鏈（BROKEN）、2＝執行錯誤（如 DB 連線失敗，非斷鏈）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import create_app_engine
from app.core.log_redaction import redact_exception_message
from app.dp.audit.models import DpAuditLog
from app.dp.audit.service import _compute_row_hash


@dataclass(frozen=True)
class ChainVerifyResult:
    """驗鏈結果。status＝OK｜BROKEN｜EMPTY；BROKEN 時帶首斷點定位資訊。"""

    status: str
    total: int
    first_broken_log_id: int | None = None
    first_broken_created_date: datetime | None = None
    first_broken_func_name: str | None = None

    @property
    def ok(self) -> bool:
        """完好（完整鏈或空表）回 True；斷鏈回 False。"""
        return self.status in ("OK", "EMPTY")


# 每批列數：一批一個交易，快照只持有到這批讀完
_BATCH_SIZE = 1000


def _is_intact(row: DpAuditLog, prev_hash: str | None) -> bool:
    expected = _compute_row_hash(
        prev_hash=prev_hash,
        module=row.module,
        func_name=row.func_name,
        action_type=row.action_type,
        result=row.result,
        operator_id=row.created_user,
        target_id=row.target_id,
        description=row.description,
        source_ip=row.source_ip,
        before_json=row.before_value,
        after_json=row.after_value,
        created_date=row.created_date,
    )
    return expected == row.row_hash


async def verify_chain(db: AsyncSession, *, batch_size: int = _BATCH_SIZE) -> ChainVerifyResult:
    """走訪 DP_AUDIT_LOG（LOG_ID ASC）重算並比對 ROW_HASH，回報首個斷鏈列。

    **分批、每批一個交易**（#905 B12）：整表在同一個交易內走訪的話，表很大時長時間持有快照，
    VACUUM 推進不了。批次之間以 `LOG_ID > 上一批最後一列` 接續，並帶著上一批最後一列的存檔 hash
    往下接鏈。

    範圍是**開始時的最大 LOG_ID** 為止：途中新寫入的列不算，持續寫入時迴圈才會結束。分批不會漏列：
    稽核寫入持有交易層級的鏈鎖（`repository.acquire_chain_lock`）到 commit，LOG_ID 依建鏈順序可見，
    不會有「較小的 LOG_ID 在較大的之後才 commit」。⚠️ 前提是所有寫入都經 `AuditLogService.log_action`；
    日後加批次匯入或回填腳本直接 INSERT 時，要重新確認這一點。

    每批各自的快照：已驗過的批次在驗證途中才被竄改的話不會被偵測，結果代表「各批讀取當下」的狀態。
    此表有擋 UPDATE / DELETE 的 trigger（#22），竄改需先停用 trigger。

    ⚠️ 每批結束時 `commit()`：呼叫端的 session 不可帶著未提交的寫入進來。
    """
    upper = await db.scalar(select(func.max(DpAuditLog.log_id)))
    await db.commit()
    if upper is None:
        return ChainVerifyResult(status="EMPTY", total=0)

    prev_hash: str | None = None
    last_id: int | None = None
    total = 0
    while True:
        stmt = select(DpAuditLog).where(DpAuditLog.log_id <= upper)
        if last_id is not None:
            stmt = stmt.where(DpAuditLog.log_id > last_id)
        rows = (await db.scalars(stmt.order_by(DpAuditLog.log_id.asc()).limit(batch_size))).all()
        broken: ChainVerifyResult | None = None
        for row in rows:
            total += 1
            if not _is_intact(row, prev_hash):
                broken = ChainVerifyResult(
                    status="BROKEN",
                    total=total,
                    first_broken_log_id=row.log_id,
                    first_broken_created_date=row.created_date,
                    first_broken_func_name=row.func_name,
                )
                break
            # 用「存檔」hash 接下一列：竄改列即使自身 hash 被一併改，下一列 prev 仍會對不上
            prev_hash = row.row_hash
            last_id = row.log_id
        # 讀完才結束交易：commit 會讓 ORM 物件過期，之後再讀欄位會觸發 lazy load
        await db.commit()
        if broken is not None:
            return broken
        if len(rows) < batch_size:
            break
    # 上界那一列在開始時已 commit、且此表擋 DELETE：最後沒讀到它，代表鏈尾在驗證途中被刪了（security review）
    if last_id != upper:
        return ChainVerifyResult(status="BROKEN", total=total, first_broken_log_id=upper)
    return ChainVerifyResult(status="OK", total=total)


def render_result(result: ChainVerifyResult) -> tuple[str, int]:
    """把驗鏈結果轉為（人可讀訊息, 退出碼）。OK/EMPTY→0、BROKEN→1。"""
    if result.status == "EMPTY":
        return ("✅ 稽核鏈完好：尚無稽核紀錄（0 筆）", 0)
    if result.status == "OK":
        return (f"✅ 稽核鏈完好：{result.total} 筆全數通過鏈式雜湊驗證", 0)
    when = result.first_broken_created_date.isoformat() if result.first_broken_created_date else "?"
    return (
        f"❌ 稽核鏈斷裂！首個異常位於 LOG_ID={result.first_broken_log_id}"
        f"（func={result.first_broken_func_name}、time={when}）；已驗 {result.total} 筆",
        1,
    )


@asynccontextmanager
async def _cli_session() -> AsyncIterator[AsyncSession]:
    """CLI 專用的 session：**不受 `DB_STATEMENT_TIMEOUT_MS` 限制**（#833 C3）。

    原本驗鏈是一句走訪全表的查詢，稽核表大到單句超過 60 秒就會被中止成退出碼 2。#905 B12 改為分批後
    單句已短，仍保留 0：一次性維運工具不該因儲存慢或批次較大就被誤殺成「執行錯誤」，例行稽核寧可跑久。
    比照 migration（`alembic/env.py`）；閒置交易逾時（#905 A2）同樣設 0。
    一次性工具不需要連線池，用 `NullPool`，結束即釋放。

    走訪已分批、每批一個交易（#905 B12），快照與 `DP_AUDIT_LOG` 的讀鎖只持有到該批讀完；與部署
    （migration 對此表 ALTER）同時執行時，ALTER 只需等當下那一批。`application_name` 讓維運能從
    `pg_stat_activity` 認出它（security review L2）。
    """
    engine = create_app_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "statement_timeout": "0",
                "idle_in_transaction_session_timeout": "0",
                "application_name": "edms-audit-verify",
            }
        },
    )
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


async def _amain() -> int:
    """CLI 進入點：開 session → 驗鏈 → 印結果 → 回退出碼。

    退出碼：0＝完好（OK/EMPTY）、1＝斷鏈（BROKEN）、2＝執行錯誤（如 DB 連線失敗）。
    以 2 區隔「執行錯誤」與「斷鏈」，避免 ops/CI 僅看退出碼時把連線失敗誤判為稽核鏈遭竄改。
    """
    try:
        async with _cli_session() as db:
            result = await verify_chain(db)
    except Exception as exc:
        # 去識別化：SQLAlchemy 例外的訊息帶 `[parameters: …]`，CLI 輸出常進排程 log（#833 C2）
        message = " ".join(redact_exception_message(exc).split())
        detail = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
        print(f"⚠️ 驗鏈執行錯誤（非斷鏈）：{detail}")
        return 2
    message, code = render_result(result)
    print(message)
    return code


if __name__ == "__main__":
    import asyncio
    import sys

    sys.exit(asyncio.run(_amain()))
