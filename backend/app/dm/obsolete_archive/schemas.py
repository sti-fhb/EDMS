"""已廢止文件查詢 schema（US10 / UCDM08 / DM06）。"""

from datetime import date, datetime

from pydantic import BaseModel


class ObsoleteQuery(BaseModel):
    """查詢條件：關鍵字（文件名 / 廢止原因）、分類、廢止日期區間（比對核准廢止之完成時間）。"""

    keyword: str | None = None
    category: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class ObsoleteDocItem(BaseModel):
    """已廢止文件清單列（FR-003）。原作者採末版〔在架版〕作者（SA 裁示 Q2=B）。"""

    doc_id: str
    doc_name: str
    latest_version_no: str | None  # 末版版號
    category_code: str
    category_name: str
    author_id: str | None  # 末版作者（DM_DOC_VERSION.CREATED_USER）
    author_name: str | None
    obsolete_date: datetime | None  # 廢止時間＝核准廢止之完成時間
    applicant_id: str | None  # 廢止申請人＝OBSOLETE 週期之 CREATED_USER
    applicant_name: str | None
    approver_id: str | None  # 核准者
    approver_name: str | None
    obsolete_reason: str | None


class ObsoleteAccess(BaseModel):
    """DM06 入口可見性（FR-001，供前端側欄逐項閘；後端另有硬閘擋直連）。"""

    can_access: bool
