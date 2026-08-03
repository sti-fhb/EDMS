"""排程總覽 / 編輯服務（US11）。

總覽唯讀列 job（含由 cron 計算之下次執行時間）；編輯僅開放 JOB_NAME / CRON_EXPR / IS_ENABLED，
JOB_ID 唯讀、HANDLER_REF / MODULE 永不可改（改 HANDLER_REF＝RCE，見 scheduler._resolve_handler 白名單）。
編輯即時套到運行中的引擎（apply_job_change），並寫稽核。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.scheduler import apply_job_change, next_run, validate_cron
from app.dp.schedules.schemas import ScheduleResponse, ScheduleUpdate
from app.services import AuditLogService

_FUNC_NAME = "DP-SCHEDULE"


class ScheduleService:
    """排程 job 查詢 / 編輯。"""

    def __init__(self, repository: ScheduleRepository | None = None, audit: AuditLogService | None = None) -> None:
        self._repo = repository or ScheduleRepository()
        self._audit = audit or AuditLogService()

    async def list_jobs(self, db: AsyncSession) -> list[ScheduleResponse]:
        """全部 job（含停用）+ 由 cron 計算之下次執行時間（停用 job 為 None）。"""
        jobs = await self._repo.list_all(db)
        result = []
        for job in jobs:
            resp = ScheduleResponse.model_validate(job)
            resp.next_run_date = next_run(job.cron_expr) if job.is_enabled else None
            result.append(resp)
        return result

    async def update_job(
        self, db: AsyncSession, *, job_id: str, data: ScheduleUpdate, operator: OperatorInfo
    ) -> ScheduleResponse:
        """編輯排程（name / cron / 啟停）+ 稽核 + 即時套到引擎。

        Raises:
            AppError: job 不存在（404 DP_SCHED_001）、cron 非法（422 DP_SCHED_002）。
        """
        job = await self._repo.get(db, job_id)
        if job is None:
            raise AppError(status_code=404, detail="排程作業不存在", error_code="DP_SCHED_001")

        try:
            validate_cron(data.cron_expr)
        except ValueError as exc:
            raise AppError(status_code=422, detail=f"cron 表達式不合法：{exc}", error_code="DP_SCHED_002") from exc

        before = {"job_name": job.job_name, "cron_expr": job.cron_expr, "is_enabled": job.is_enabled}
        now = utcnow()
        await self._repo.update_job(
            db,
            job=job,
            job_name=data.job_name,
            cron_expr=data.cron_expr,
            is_enabled=data.is_enabled,
            operator_id=operator.user_id,
            now=now,
        )
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=job_id,
            description="編輯排程作業",
            before_value=before,
            after_value={"job_name": data.job_name, "cron_expr": data.cron_expr, "is_enabled": data.is_enabled},
        )
        # 即時套到運行中的引擎（引擎未啟動則 no-op、下次啟動生效）；DB 為權威，若後續 commit 失敗於重啟自癒。
        apply_job_change(job_id, cron_expr=data.cron_expr, is_enabled=data.is_enabled, handler_ref=job.handler_ref)

        resp = ScheduleResponse.model_validate(job)
        resp.next_run_date = next_run(job.cron_expr) if job.is_enabled else None
        return resp
