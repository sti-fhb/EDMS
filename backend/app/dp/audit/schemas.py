"""稽核查詢 schema（US10 / dp-audit，唯讀）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    """單筆稽核紀錄（列表 + 明細共用；明細額外呈現 description / before / after）。

    operator_name / operator_email 由查詢時 LEFT JOIN DP_USER 解析（SYSTEM 或已不存在 USER_ID 時為 None）。
    func_label 為 func_name 之中文顯示名；target_display 為 target_id 解析後之可讀名稱（查無回原 target_id）。
    before_value / after_value 為 JSON 字串（TEXT 欄），由前端 parse 後格式化呈現。
    """

    log_id: int
    created_date: datetime
    operator_id: str
    operator_name: Optional[str]
    operator_email: Optional[str]
    module: str
    func_name: str
    func_label: str
    action_type: str
    result: str
    target_id: Optional[str]
    target_display: Optional[str]
    source_ip: Optional[str]
    description: Optional[str]
    before_value: Optional[str]
    after_value: Optional[str]
