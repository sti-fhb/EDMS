from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.core.schema_types import NormalizedEmailStr, SafeNameStr

# 姓名一律走共用型別（strip + 長度 + 拒控制字元，理由見 core/schema_types.py，#225）
_NameStr = SafeNameStr

#: 使用者搜尋關鍵字（姓名 / Email 模糊比對）之長度上限 = 比對欄位中較長者 `DP_USER.EMAIL` 的
#: VARCHAR(255)。**凡是把關鍵字交給 `UsersService.list_users` / `list_invites` 的端點都必須用它**，
#: 目前有 `dp/users`（清單、邀請清單）與 `dp/roles`（權限指派清單）三處——它們是同一個查詢，
#: 上限各寫各的會讓同一組關鍵字在一頁搜得到、另一頁 422（#513 Security LOW-1 即為此）。
#: ⚠️ 此上限只防過長字串，**不含 LIKE 萬用字元跳脫**（`%` / `_` 仍為樣式字元），見 #275。
USER_KEYWORD_MAX_LEN = 255


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
