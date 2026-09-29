"""排程總覽 schema（US11 / dp-schedule，唯讀）。"""

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints

#: 對齊 `DP_SCHEDULE.DESCRIPTION VARCHAR(200)`：超長在 INSERT 時會由 DB 拋錯、落成 500 而非 422
_DescStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ScheduleResponse(BaseModel):
    """單一排程 job（總覽清單）。`next_run_date` 由 cron 於查詢時計算（停用 job 為 None）。"""

    model_config = {"from_attributes": True}

    job_id: str
    job_name: str
    #: 這支 job 在做什麼（#311）；可於 UI 編輯（原為唯讀，改為免 migration 即可修正說明文字）。
    description: Optional[str] = None
    module: str
    cron_expr: str
    is_enabled: bool
    last_run_date: Optional[datetime]
    last_run_status: Optional[str]
    next_run_date: Optional[datetime] = None


class ScheduleUpdate(BaseModel):
    """編輯排程（JOB_NAME / DESCRIPTION / CRON_EXPR / IS_ENABLED；JOB_ID / HANDLER_REF / MODULE 不可改）。

    `description` 未帶＝維持原值（不讓未送此欄的呼叫端意外清掉說明）；帶空字串或 null＝清空。
    """

    job_name: str = Field(min_length=1, max_length=100)
    description: Optional[_DescStr] = None
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
