"""US4 使用者管理 schema 驗證 unit 測試（不連 DB）。"""

import pytest
from pydantic import ValidationError

from app.dp.users.schemas import UserCreate, UserStatusUpdate, UserUpdate

pytestmark = pytest.mark.unit


def test_user_create_valid():
    m = UserCreate(email="a@b.com", user_name=" 小明 ", password="Abcd1234")
    assert m.email == "a@b.com"
    assert m.user_name == "小明"  # 去頭尾空白


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "@b.com", "a b@c.com"])
def test_user_create_bad_email_rejected(email):
    with pytest.raises(ValidationError):
        UserCreate(email=email, user_name="小明", password="Abcd1234")


def test_user_create_empty_name_rejected():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", user_name="   ", password="Abcd1234")


def test_user_update_requires_name_and_email():
    with pytest.raises(ValidationError):
        UserUpdate(user_name="只有姓名")  # 缺 email


@pytest.mark.parametrize("action", ["disable", "enable"])
def test_status_action_valid(action):
    assert UserStatusUpdate(action=action).action == action


def test_status_action_invalid_rejected():
    with pytest.raises(ValidationError):
        UserStatusUpdate(action="delete")
