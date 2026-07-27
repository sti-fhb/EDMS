"""#35 email 大小寫正規化 unit 測試（schema 層，不連 DB）。

各進入點的 email 一律 `strip + lower`，使下游查詢 / 限流 key / 冷卻 key / 儲存一致。
登入不套格式 regex（維持「格式錯→認證失敗」而非 422）；其餘進入點沿用既有輕量 regex（不引 EmailStr）。
"""

import pytest
from pydantic import ValidationError

from app.dp.user.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
)
from app.dp.users.schemas import UserCreate

pytestmark = pytest.mark.unit

_MIXED = "  Foo.Bar@Example.COM  "
_NORMALIZED = "foo.bar@example.com"


def test_login_email_normalized_and_no_format_check():
    # 登入：strip + lower
    assert LoginRequest(email=_MIXED, password="x").email == _NORMALIZED
    # 登入不做格式驗證：畸形 email 不 422（只正規化，交由認證失敗處理）
    assert LoginRequest(email="NotAnEmail", password="x").email == "notanemail"


@pytest.mark.parametrize(
    "model_kwargs",
    [
        lambda e: RegisterRequest(email=e, user_name="王小明", password="Abcd1234", confirm_password="Abcd1234"),
        lambda e: ForgotPasswordRequest(email=e),
        lambda e: ResendVerificationRequest(email=e),
        lambda e: UserCreate(email=e, user_name="王小明"),
    ],
)
def test_email_bearing_schemas_normalize(model_kwargs):
    assert model_kwargs(_MIXED).email == _NORMALIZED


@pytest.mark.parametrize(
    "builder",
    [
        lambda e: RegisterRequest(email=e, user_name="王小明", password="Abcd1234", confirm_password="Abcd1234"),
        lambda e: ForgotPasswordRequest(email=e),
        lambda e: ResendVerificationRequest(email=e),
        lambda e: UserCreate(email=e, user_name="王小明"),
    ],
)
def test_format_checked_schemas_reject_malformed(builder):
    # 有格式檢核的進入點：畸形 email 仍 422（regex 未放行）
    with pytest.raises(ValidationError):
        builder("not-an-email")
