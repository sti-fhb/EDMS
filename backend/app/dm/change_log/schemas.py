"""文件變更歷程查詢 schema（US11 / UCDM10 / DM08）。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

# 公開變更歷程僅發布 / 廢止兩類（DM_CHANGE_LOG 依設計只寫這兩類，FR-005 由來源保證）。
Operation = Literal["PUBLISH", "OBSOLETE"]


class ChangeLogQuery(BaseModel):
    """查詢條件：日期區間（比對 OPERATION_TIME）、申請人 / 核准人（帳號或姓名）、操作類型。"""

    keyword: str | None = None  # 申請人 / 核准人之帳號或姓名
    operation: Operation | None = None  # None=全部
    date_from: date | None = None
    date_to: date | None = None


class ChangeLogEntry(BaseModel):
    """變更歷程清單列（FR-003）。備註：發布＝變更摘要、廢止＝廢止原因。"""

    change_log_id: int
    operation_time: datetime | None
    operation: Operation  # PUBLISH / OBSOLETE（前端呈現發布 / 廢止 badge）
    applicant_id: str
    applicant_name: str | None
    approver_id: str
    approver_name: str | None
    doc_id: str
    doc_name: str
    version_no: str | None
    note: str | None
