from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, StringConstraints

# Email 格式：沿用 US1/US2 輕量 regex（不引 email-validator 依賴）
_EmailStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
_NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


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
    """管理者代建帳號請求（US4 FR-03）。初始密碼複雜度 / Email 唯一由服務層權威檢核。"""

    email: _EmailStr
    user_name: _NameStr
    password: str


class UserUpdate(BaseModel):
    """管理者維護基本資料請求（US4 FR-06）。姓名 / Email 直接生效（不走驗證信）。"""

    user_name: _NameStr
    email: _EmailStr


class UserStatusUpdate(BaseModel):
    """停用 / 啟用請求（US4 FR-04）。action 由 schema 收斂，非法值於 422 擋下。"""

    action: Literal["disable", "enable"]
