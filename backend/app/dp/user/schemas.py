from pydantic import BaseModel


class LoginRequest(BaseModel):
    """登入請求。"""

    email: str
    password: str


class RegisterRequest(BaseModel):
    """自助註冊請求（US2）。Email 格式由前端 Zod 把關，後端沿用 str 避免 email-validator 依賴。"""

    email: str
    user_name: str
    password: str
    confirm_password: str


class LoginResponse(BaseModel):
    """登入回應：JWT access token + 是否需強制變更密碼。"""

    access_token: str
    must_change_pwd: bool


class TokenResponse(BaseModel):
    """換發回應：僅新 JWT access token（沿用原 auth_time）。"""

    access_token: str


class ModuleRoleStatus(BaseModel):
    """單一模組於入口頁的可進入狀態。"""

    has_role: bool


class ModuleSummary(BaseModel):
    """入口頁模組摘要：各模組是否具任一角色（決定卡片可進入 / 未開通）。"""

    et: ModuleRoleStatus
    dm: ModuleRoleStatus
