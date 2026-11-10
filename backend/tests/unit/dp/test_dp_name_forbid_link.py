"""姓名欄位禁止網址（#942）：四個姓名進入點皆經 `SafeNameStr`。

姓名會被代入系統通知信內文；自助註冊與 Email 變更可指定任意收件信箱，姓名中的網址會以正式
寄件人寄到他人信箱。姓名沒有放網址的正當需求，故一律拒絕（不區分是否為本系統網域）。
"""

import pytest
from pydantic import BaseModel, ValidationError

from app.dp.user.schemas import NameUpdate, RegisterRequest
from app.dp.users.schemas import UserCreate, UserUpdate

pytestmark = pytest.mark.unit

_ENTRY_POINTS: list[tuple[str, type[BaseModel], dict[str, str]]] = [
    ("自助註冊", RegisterRequest, {"email": "a@example.com"}),
    ("本人改姓名", NameUpdate, {}),
    ("管理者新增", UserCreate, {"email": "a@example.com"}),
    ("管理者修改", UserUpdate, {}),
]
_IDS = [name for name, _, _ in _ENTRY_POINTS]


@pytest.mark.parametrize(("_name", "model", "extra"), _ENTRY_POINTS, ids=_IDS)
@pytest.mark.parametrize(
    "user_name",
    [
        "帳號異常請至 https://evil.example.com 處理",
        "WWW.evil.example.com",
        "ｈｔｔｐｓ://evil.example.com",
        "//evil.example.com",
        chr(92) * 2 + "evil.example.com" + chr(92) + "share",  # UNC 路徑
    ],
)
def test_name_with_link_rejected(_name, model, extra, user_name):
    with pytest.raises(ValidationError) as exc:
        model(**extra, user_name=user_name)
    assert [e["loc"][-1] for e in exc.value.errors()] == ["user_name"]


@pytest.mark.parametrize(("_name", "model", "extra"), _ENTRY_POINTS, ids=_IDS)
@pytest.mark.parametrize("user_name", ["王小明", "J. Smith", "Mary-Jane Watson", "A/B 組"])
def test_normal_name_passes(_name, model, extra, user_name):
    assert model(**extra, user_name=user_name).user_name == user_name


def test_existing_rules_still_apply():
    """原有的 strip、長度、控制字元檢核不受影響（正向錨點：新驗證器不能取代舊規則）。"""
    assert NameUpdate(user_name="  王小明  ").user_name == "王小明"
    with pytest.raises(ValidationError):
        NameUpdate(user_name="王\n小明")
    with pytest.raises(ValidationError):
        NameUpdate(user_name="王" * 51)
