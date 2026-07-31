"""排程總覽 schema（US11 / dp-schedule，唯讀）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ScheduleResponse(BaseModel):
    """單一排程 job（總覽清單）。"""

    model_config = {"from_attributes": True}

    job_id: str
    job_name: str
    module: str
    cron_expr: str
    is_enabled: bool
    last_run_date: Optional[datetime]
    last_run_status: Optional[str]


class ScheduleLogResponse(BaseModel):
    """單筆排程執行歷程。"""

    model_config = {"from_attributes": True}

    log_id: int
    job_id: str
    start_date: datetime
    end_date: Optional[datetime]
    status: str
    error_msg: Optional[str]
