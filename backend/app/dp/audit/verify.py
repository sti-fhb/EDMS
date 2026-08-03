"""稽核 ROW_HASH 鏈驗證工具（T052，唯讀）。

依 `LOG_ID` 遞增（＝建鏈序，見 service.get_last_row_hash 取 desc limit 1）走訪
`DP_AUDIT_LOG` 全表，逐列重算鏈式雜湊並與存檔 `ROW_HASH` 比對；`prev` 以「前一列的
**存檔** ROW_HASH」接鏈——任一列遭竄改（含攻擊者一併改該列自身 hash 但無法連改後續）
都會在該列或下一列現形。回報最早（`LOG_ID` 最小）的斷鏈位置。

重用 service._compute_row_hash（同一 canonical hash 定義），避免驗證端與寫入端漂移。

ops 例行稽核 / CI 可直接執行：
    python -m app.dp.audit.verify
退出碼：0＝完好（OK / 空表 EMPTY）、1＝斷鏈（BROKEN）。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def verify_chain(db: AsyncSession) -> ChainVerifyResult:
    """走訪 DP_AUDIT_LOG（LOG_ID ASC）重算並比對 ROW_HASH，回報首個斷鏈列。

    以 stream 逐列讀取避免大表一次載入記憶體。
    """
    stmt = select(DpAuditLog).order_by(DpAuditLog.log_id.asc())
    prev_hash: str | None = None
    total = 0

    result = await db.stream(stmt)
    async for row in result.scalars():
        total += 1
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
        if expected != row.row_hash:
            return ChainVerifyResult(
                status="BROKEN",
                total=total,
                first_broken_log_id=row.log_id,
                first_broken_created_date=row.created_date,
                first_broken_func_name=row.func_name,
            )
        # 用「存檔」hash 接下一列：竄改列即使自身 hash 被一併改，下一列 prev 仍會對不上
        prev_hash = row.row_hash

    return ChainVerifyResult(status="EMPTY" if total == 0 else "OK", total=total)


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


async def _amain() -> int:
    """CLI 進入點：開 session → 驗鏈 → 印結果 → 回退出碼。"""
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await verify_chain(db)
    message, code = render_result(result)
    print(message)
    return code


if __name__ == "__main__":
    import asyncio
    import sys

    sys.exit(asyncio.run(_amain()))
