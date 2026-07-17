from pydantic import BaseModel


class LoginRequest(BaseModel):
    """登入請求。"""

    email: str
    password: str


class LoginResponse(BaseModel):
    """登入回應：JWT access token + 是否需強制變更密碼。"""

    access_token: str
    must_change_pwd: bool
