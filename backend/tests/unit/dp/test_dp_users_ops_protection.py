"""廠商維運帳號（`edmsops`）於使用者管理之保護規則單元測試（#927）。

不論操作者是誰（含本帳號自己），管理者路徑不可停用、不可修改姓名；解鎖與啟用不擋。
每條「擋」都配一條同操作對一般帳號放行的對照，確認擋下的理由是「目標為維運帳號」。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AppError
from app.core.operator import OperatorInfo
from app.core.ops_account import OPS_USER_ID
from app.dp.users.schemas import UserUpdate

pytestmark = pytest.mark.unit

_OTHER = "U0000001"


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="某人",
        email=f"{user_id.lower()}@example.com",
        status="ACTIVE",
        locked_until=None,
        last_login_date=None,
        created_date=None,
        login_fail_count=0,
    )


def _service() -> tuple["UsersService", AsyncMock]:  # noqa: F821 — 型別僅供閱讀，見下方函式層 import
    # ⚠️ 函式層 import：模組層先載入 `app.dp.users.service` 會觸發 `app.services` ↔ `app.dp.users`
    # 之間的循環 import（同 test_dp_query_limits.py 的處理）
    from app.dp.users.service import UsersService

    repo = AsyncMock()
    repo.get_by_id.side_effect = lambda _db, uid: _user(uid)
    return UsersService(repository=repo, audit=AsyncMock()), repo


@pytest.mark.parametrize("operator_id", ["ADMIN01", OPS_USER_ID])
async def test_disable_ops_account_blocked(operator_id: str) -> None:
    """任何操作者（含維運帳號自己）停用維運帳號 → 403 DP_USER_012，且不寫入。"""
    svc, repo = _service()
    with pytest.raises(AppError) as e:
        await svc.set_status(None, user_id=OPS_USER_ID, action="disable", operator=OperatorInfo(user_id=operator_id))
    assert (e.value.status_code, e.value.error_code) == (403, "DP_USER_012")
    repo.set_status.assert_not_awaited()


async def test_disable_other_account_allowed() -> None:
    """對照：停用一般帳號照常寫入。"""
    svc, repo = _service()
    await svc.set_status(None, user_id=_OTHER, action="disable", operator=OperatorInfo(user_id="ADMIN01"))
    repo.set_status.assert_awaited_once()


async def test_enable_ops_account_allowed() -> None:
    """啟用維運帳號不擋（保護的是「不被停用」，啟用只會讓它回到可用狀態）。"""
    svc, repo = _service()
    await svc.set_status(None, user_id=OPS_USER_ID, action="enable", operator=OperatorInfo(user_id="ADMIN01"))
    repo.set_status.assert_awaited_once()


@pytest.mark.parametrize("operator_id", ["ADMIN01", OPS_USER_ID])
async def test_rename_ops_account_blocked(operator_id: str) -> None:
    """任何操作者經使用者管理改維運帳號姓名 → 403 DP_USER_013，且不寫入。"""
    svc, repo = _service()
    with pytest.raises(AppError) as e:
        await svc.update_basic(
            None, user_id=OPS_USER_ID, data=UserUpdate(user_name="新名字"), operator=OperatorInfo(user_id=operator_id)
        )
    assert (e.value.status_code, e.value.error_code) == (403, "DP_USER_013")
    repo.update_name.assert_not_awaited()


async def test_rename_other_account_allowed() -> None:
    """對照：改一般帳號姓名照常寫入。"""
    svc, repo = _service()
    await svc.update_basic(
        None, user_id=_OTHER, data=UserUpdate(user_name="新名字"), operator=OperatorInfo(user_id="ADMIN01")
    )
    repo.update_name.assert_awaited_once()


async def test_unlock_ops_account_allowed() -> None:
    """解鎖維運帳號不擋——被人連打錯密碼鎖住時，院方管理者要能幫忙解開。"""
    svc, repo = _service()
    await svc.unlock(None, user_id=OPS_USER_ID, operator=OperatorInfo(user_id="ADMIN01"))
    repo.unlock.assert_awaited_once()
