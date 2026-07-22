from typing import Annotated

from pydantic import BaseModel, StringConstraints


class LoginRequest(BaseModel):
    """登入請求。"""

    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    """忘記密碼申請請求（US3）。僅需 Email；一律回相同訊息（防列舉）。格式把關與 RegisterRequest 一致。"""

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    ]


class ResetPasswordRequest(BaseModel):
    """密碼重設請求（US3）。token 為信中連結明文；新密碼複雜度 / 重複性由服務層權威檢核。"""

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: str
    confirm_password: str


class RegisterRequest(BaseModel):
    """自助註冊請求（US2）。

    匿名端點可繞過前端，故後端於 schema 層即把關長度與 Email 基本格式（去頭尾空白後）：
    - EMAIL / USER_NAME 對齊 DP_USER 欄位長度（255 / 50），不合規走 422（RequestValidationError），
      避免超長字串落到 DB 層例外變成 500。
    - Email 格式以輕量 regex 檢核（不引 email-validator 依賴，沿用 US1 決策）。
    - password 不 strip（前後空白可為合法密碼字元）；複雜度 / 兩次一致由服務層權威檢核。
    """

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    ]
    user_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    password: str
    confirm_password: str


class VerifyEmailRequest(BaseModel):
    """註冊驗證請求（US2 #56）。token 為信中連結明文；效期 / 有效性由服務層權威檢核。"""

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ResendVerificationRequest(BaseModel):
    """重寄註冊驗證信請求（US2 #56）。僅需 Email；一律回相同訊息（防列舉）。格式同 RegisterRequest。"""

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    ]


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
