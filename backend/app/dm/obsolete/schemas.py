"""文件廢止申請（US8 / UCDM05 / DM02）schema。"""

from pydantic import BaseModel


class InitiateObsoleteResult(BaseModel):
    """發起廢止申請結果。"""

    review_id: int
    doc_status: str  # PENDING_OBSOLETE
    notified: int  # 排入 Email 之收件數（0=範本停用 / 審核者無 Email）
