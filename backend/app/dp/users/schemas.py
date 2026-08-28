from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.core.schema_types import NormalizedEmailStr, SafeNameStr

# 姓名一律走共用型別（strip + 長度 + 拒控制字元，理由見 core/schema_types.py，#225）
_NameStr = SafeNameStr


class UserResponse(BaseModel):
    """使用者清單 / 單筆回應（管理者檢視）。

    `status` 為原始 DP_USER.STATUS（ACTIVE / DISABLED）；`locked_until` 為鎖定截止時間，
    「已鎖定」由前端以 `locked_until > now` 衍生呈現（避免序列化時取系統時間）。密碼欄位一律不外露。
    """

    model_config = {"from_attributes": True}

    user_id: str
    user_name: str
    email: str
    status: str
    locked_until: Optional[datetime]
    last_login_date: Optional[datetime]
    created_date: Optional[datetime]


class UserCreate(BaseModel):
    """管理者建立帳號請求（US4 FR-03，#67 改邀請流程）。

    管理者**不設密碼**——僅填 Email / 姓名，系統寄邀請信、使用者自設密碼後啟用。
    Email 唯一由服務層權威檢核。
    """

    email: NormalizedEmailStr
    user_name: _NameStr


class UserUpdate(BaseModel):
    """管理者維護基本資料請求（US4 FR-12，#67）。僅可改**姓名**；Email 為登入帳號、唯讀不可代改。"""

    user_name: _NameStr


class UserStatusUpdate(BaseModel):
    """停用 / 啟用請求（US4 FR-04）。action 由 schema 收斂，非法值於 422 擋下。"""

    action: Literal["disable", "enable"]


class InviteResponse(BaseModel):
    """待啟用邀請清單回應（US4 #67，ADMIN_INVITE）。

    來源為 `DP_PENDING_REGISTRATION`（尚無 USER_ID，以 `invite_id` 為對外識別碼）。
    「邀請狀態」（有效中 / 已逾期）由前端以 `expires_date` vs now 衍生（同 UserResponse.locked_until）。
    """

    model_config = {"from_attributes": True}

    invite_id: Optional[str]
    email: str
    user_name: str
    created_date: Optional[datetime]
    expires_date: datetime
