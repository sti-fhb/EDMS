"""排程總覽 schema（US11 / dp-schedule，唯讀）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScheduleResponse(BaseModel):
    """單一排程 job（總覽清單）。`next_run_date` 由 cron 於查詢時計算（停用 job 為 None）。"""

    model_config = {"from_attributes": True}

    job_id: str
    job_name: str
    module: str
    cron_expr: str
    is_enabled: bool
    last_run_date: Optional[datetime]
    last_run_status: Optional[str]
    next_run_date: Optional[datetime] = None


class ScheduleUpdate(BaseModel):
    """編輯排程（僅 JOB_NAME / CRON_EXPR / IS_ENABLED；JOB_ID / HANDLER_REF / MODULE 不可改）。"""

    job_name: str = Field(min_length=1, max_length=100)
    cron_expr: str = Field(min_length=1, max_length=50)
    is_enabled: bool


class ScheduleLogResponse(BaseModel):
    """單筆排程執行歷程。"""

    model_config = {"from_attributes": True}

    log_id: int
    job_id: str
    start_date: datetime
    end_date: Optional[datetime]
    status: str
    error_msg: Optional[str]
