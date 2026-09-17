"""排程總覽 / 編輯服務（US11）。

總覽唯讀列 job（含由 cron 計算之下次執行時間）；編輯僅開放 JOB_NAME / CRON_EXPR / IS_ENABLED，
JOB_ID 唯讀、HANDLER_REF / MODULE 永不可改（改 HANDLER_REF＝RCE，見 scheduler._resolve_handler 白名單）。
編輯即時套到運行中的引擎（apply_job_change），並寫稽核。
"""

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import BACKOFFICE_MODULES, module_admin_gate
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.schedules.repository import ScheduleRepository
from app.dp.schedules.scheduler import apply_job_change, next_run, validate_cron
from app.dp.schedules.schemas import ScheduleResponse, ScheduleUpdate
from app.services import AuditLogService

_FUNC_NAME = "DP-SCHEDULE"

#: 無對應模組管理者角色、由後台共用維護的排程所屬模組。
#:
#: ⚠️ **把 `"DP"` 從這裡拿掉會讓平台排程變成沒有任何人能維護。** 平台沒有「DP 管理者」
#: 這個角色概念（`module_admin_gate` 沒有 `DP` 的 checker），因此一律以所屬模組判定時，
#: `SCHDP001` 會對每一個人都回 403——包含所有後台管理者。明列於此者回退為 router-level
#: 的同一組門檻（ET 或 DM 任一管理者）。
#:
#: 明列而非以「有沒有註冊 checker」推導：後者方向是 fail-open。完整理由見 `_ensure_may_edit`。
_SHARED_MODULES: Final[frozenset[str]] = frozenset({"DP"})


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

    async def _ensure_may_edit(self, db: AsyncSession, *, job, operator: OperatorInfo) -> None:
        """編輯某 job 需為**該 job 所屬模組**的管理者。

        ## 為何 router-level 的「ET 或 DM 任一管理者」對編輯不夠

        總覽是唯讀共用項，任一模組管理者都看得到全部 job，那沒問題。但 `PUT` 會改
        `CRON_EXPR` 與 `IS_ENABLED`，而排程驅動的是各模組的業務批次——DM 管理者能停用
        ET 的成績結清、ET 管理者能改 DM 的簽核催辦頻率，而**畫面上不會有任何異常**：
        job 只是安靜地不再執行。這類「改動後沒有錯誤訊息、只有事情不再發生」的權限
        缺口最難察覺。

        ## 平台自身的排程（`MODULE='DP'`）維持共用

        平台沒有「DP 管理者」這個角色概念（`module_admin_gate` 沒有 `DP` 的 checker），
        一律以所屬模組判定會讓 `SCHDP001` 變成**沒有任何人**能維護。故明列於
        `_SHARED_MODULES` 者回退為 router-level 的同一組門檻（ET 或 DM 任一管理者）——與
        本次變更前的行為相同，不新增也不縮減平台排程的可維護性。

        ⚠️ **判準是「明列於共用清單」而非「沒有註冊 checker」**。後者寫起來更短，但方向
        是 fail-open：日後任何新模組只要忘記呼叫 `module_admin_gate.register`（那只是
        `main.py` 的一行 import 期呼叫，漏掉不會有任何錯誤訊息），它的排程就會**靜默地**
        變成全體後台管理者可編輯。`ModuleAdminGate` 其餘每一條路徑（未註冊、checker 拋
        例外、回傳非嚴格 `True`）都是 fail-closed，這裡不該是唯一的例外。

        Raises:
            AppError: 非該模組管理者（403 DP_AUTH_006，與 `require_module_admin` 同碼）。
        """
        if job.module in _SHARED_MODULES:
            allowed = await module_admin_gate.is_any_module_admin(BACKOFFICE_MODULES, operator.user_id, db)
        else:
            allowed = await module_admin_gate.is_module_admin(job.module, operator.user_id, db)
        if not allowed:
            raise AppError(status_code=403, detail="需要模組管理者權限", error_code="DP_AUTH_006")

    async def update_job(
        self, db: AsyncSession, *, job_id: str, data: ScheduleUpdate, operator: OperatorInfo
    ) -> ScheduleResponse:
        """編輯排程（name / cron / 啟停）+ 稽核 + 即時套到引擎。

        Raises:
            AppError: job 不存在（404 DP_SCHED_001）、**非該 job 所屬模組之管理者**
                （403 DP_AUTH_006，見 `_ensure_may_edit`）、cron 非法（422 DP_SCHED_002）。
        """
        job = await self._repo.get(db, job_id)
        if job is None:
            raise AppError(status_code=404, detail="排程作業不存在", error_code="DP_SCHED_001")
        await self._ensure_may_edit(db, job=job, operator=operator)

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
