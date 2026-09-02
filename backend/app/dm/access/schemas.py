"""DM 共用存取判定 schema。"""

from pydantic import BaseModel


class AdminAccess(BaseModel):
    """DM 管理者入口可見性（共用，供側欄逐項閘 US10/11/13）。"""

    can_access: bool


class ReviewerAccess(BaseModel):
    """DM 審核者入口可見性（#250，供側欄決定「簽核中心」是否顯示）。"""

    can_access: bool
