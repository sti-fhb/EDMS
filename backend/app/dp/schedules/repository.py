"""排程註冊表 / 執行歷程存取（US11）。

`DP_SCHEDULE_LOG` 為 append-only：每次執行結束單筆 INSERT（含起訖 / 結果 / 錯誤），不做 UPDATE；
`DP_SCHEDULE.LAST_RUN_*` 允許更新。
"""

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.schedules.models import DpSchedule, DpScheduleLog


class ScheduleRepository:
    """DP_SCHEDULE / DP_SCHEDULE_LOG 存取。"""

    async def list_enabled(self, db: AsyncSession) -> list[DpSchedule]:
        """啟用中（IS_ENABLED=true）之 job（引擎啟動時載入註冊）。"""
        stmt = select(DpSchedule).where(DpSchedule.deleted == 0, DpSchedule.is_enabled.is_(True))
        return list((await db.execute(stmt)).scalars().all())

    async def list_all(self, db: AsyncSession) -> list[DpSchedule]:
        """全部 job（總覽清單，含停用；依 JOB_ID）。"""
        stmt = select(DpSchedule).where(DpSchedule.deleted == 0).order_by(DpSchedule.job_id)
        return list((await db.execute(stmt)).scalars().all())

    async def get(self, db: AsyncSession, job_id: str) -> DpSchedule | None:
        stmt = select(DpSchedule).where(DpSchedule.job_id == job_id, DpSchedule.deleted == 0)
        return (await db.execute(stmt)).scalar_one_or_none()

    def build_logs_stmt(self, job_id: str) -> Select:
        """某 job 之執行歷程 Select（時間倒序，交 paginate）。"""
        return (
            select(DpScheduleLog)
            .where(DpScheduleLog.job_id == job_id)
            .order_by(DpScheduleLog.start_date.desc(), DpScheduleLog.log_id.desc())
        )

    async def insert_log(
        self,
        db: AsyncSession,
        *,
        job_id: str,
        start_date: datetime,
        end_date: datetime | None,
        status: str,
        error_msg: str | None,
    ) -> None:
        """新增一列執行歷程（append-only，單筆 INSERT）並 flush。"""
        db.add(
            DpScheduleLog(
                job_id=job_id,
                start_date=start_date,
                end_date=end_date,
                status=status,
                error_msg=error_msg,
                created_user="SYSTEM",
                created_date=start_date,
            )
        )
        await db.flush()

    async def update_last_run(self, db: AsyncSession, *, job_id: str, run_date: datetime, status: str) -> None:
        """更新 DP_SCHEDULE 之 LAST_RUN_DATE / LAST_RUN_STATUS（+ 稽核欄位 SYSTEM）並 flush。"""
        job = await self.get(db, job_id)
        if job is not None:
            job.last_run_date = run_date
            job.last_run_status = status
            job.updated_user = "SYSTEM"
            job.updated_date = run_date
            await db.flush()
