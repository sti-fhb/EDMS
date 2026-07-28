from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.core.schema_types import LoginEmailStr, NormalizedEmailStr


class LoginRequest(BaseModel):
    """登入請求。email 正規化（#35）：strip + lower（不做格式驗證，格式錯→認證失敗）。"""

    email: LoginEmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """忘記密碼申請請求（US3）。僅需 Email；一律回相同訊息（防列舉）。email 正規化同註冊（#35）。"""

    email: NormalizedEmailStr


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
    - Email 格式以輕量 regex 檢核（不引 email-validator 依賴，沿用 US1 決策）；並 strip + lower 正規化（#35）。
    - password 不 strip（前後空白可為合法密碼字元）；複雜度 / 兩次一致由服務層權威檢核。
    """

    email: NormalizedEmailStr
    user_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    password: str
    confirm_password: str


class VerifyEmailRequest(BaseModel):
    """註冊驗證請求（US2 #56）。token 為信中連結明文；效期 / 有效性由服務層權威檢核。"""

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ActivateAccountRequest(BaseModel):
    """帳號啟用請求（US4 #67 管理者邀請）。token 為邀請信連結明文；使用者於啟用頁自設密碼。

    密碼複雜度 / 兩次一致 / token 有效性（僅 ADMIN_INVITE）由服務層權威檢核。
    """

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: str
    confirm_password: str


class ResendVerificationRequest(BaseModel):
    """重寄註冊驗證信請求（US2 #56）。僅需 Email；一律回相同訊息（防列舉）。email 正規化同註冊（#35）。"""

    email: NormalizedEmailStr


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


class MeResponse(BaseModel):
    """個人資料（US8）：本人姓名 / 帳號（Email）/ 待驗證新信箱。"""

    model_config = {"from_attributes": True}

    user_id: str
    email: str
    user_name: str
    # 有值代表已申請 Email 變更、尚未驗證（供前端顯示「變更審核中」）；None 代表無待驗證變更。
    pending_email: str | None = None


class NameUpdate(BaseModel):
    """姓名變更請求（US8）。長度對齊 DP_USER.USER_NAME（50）。"""

    user_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class PasswordChange(BaseModel):
    """密碼變更請求（US8）。密碼不 strip（前後空白可為合法字元）；複雜度 / 重複性由服務層權威檢核。

    僅於 schema 層擋空字串（min_length=1，讓明顯無效輸入更早以 422 攔下）；長度 / 複雜度門檻仍由 service 權威。
    """

    old_password: Annotated[str, StringConstraints(min_length=1)]
    new_password: Annotated[str, StringConstraints(min_length=1)]
    confirm_password: Annotated[str, StringConstraints(min_length=1)]


class EmailChangeRequest(BaseModel):
    """Email 變更申請請求（US8）。新 Email 正規化同註冊（#35：strip + lower），使儲存 / 唯一性檢核
    與登入（LoginEmailStr）一致——否則存入混合大小寫，登入以小寫查詢會對不上。唯一性由服務層權威檢核。"""

    new_email: NormalizedEmailStr


class EmailChangeVerify(BaseModel):
    """Email 變更驗證請求（US8）。token 為信中連結明文；效期 / 有效性由服務層權威檢核。"""

    token: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class PasswordPolicyResponse(BaseModel):
    """公開密碼政策（US8 / 併 #77）：供變更密碼 / 註冊 / 重設頁動態渲染提示；僅非機密數值。"""

    min_len: int
    admin_min_len: int
    char_types: int
    history_count: int
    expiry_days: int
