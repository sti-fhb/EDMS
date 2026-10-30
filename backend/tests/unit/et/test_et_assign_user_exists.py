"""ET 角色指派須先確認目標帳號存在（#188 A2；以替身取代 DB 與帳號查詢）。

`EtAssignService.assign` 為 `ET_USER_ROLE` / `ET_USER_TAG` 之權威寫入口，原本可為任意
字串建立角色列（含 ADMIN），留下孤兒授權列。DP 端之 `_require_usable_target` 對查無帳號
**刻意放行**（模組角色表無 FK 至 `DP_USER`），故存在性只能由 ET 這一側把關。

驗的是「擋在任何讀寫之前」：替身 DB 一旦被碰就失敗，不需真 DB。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppError
from app.dp.users.account_status import AccountStatus
from app.et.constants import ROLE_ADMIN, ROLE_STUDENT
from app.et.roles.assign_service import EtAssignService
from app.services import AccountQueryService

pytestmark = pytest.mark.unit


def _accounts(*, exists: bool) -> AccountQueryService:
    accounts = MagicMock(spec=AccountQueryService)
    accounts.exists = AsyncMock(return_value=exists)
    return accounts


def _untouchable_db() -> MagicMock:
    """任何 DB 存取皆視為違規——查無帳號時不得讀現況、更不得寫入。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("查無帳號仍讀取 DB"))
    db.scalar = AsyncMock(side_effect=AssertionError("查無帳號仍讀取 DB"))
    db.flush = AsyncMock(side_effect=AssertionError("查無帳號仍寫入 DB"))
    db.add = MagicMock(side_effect=AssertionError("查無帳號仍寫入 DB"))
    return db


async def test_查無帳號_拒絕指派且不碰_db():
    svc = EtAssignService(accounts=_accounts(exists=False), audit=AsyncMock())

    with pytest.raises(AppError) as e:
        await svc.assign(_untouchable_db(), user_id="ghost", roles={ROLE_ADMIN}, groups=set(), operator_id="adm")

    assert (e.value.status_code, e.value.error_code) == (404, "ET_ROLE_004")
    svc._audit.log_action.assert_not_called()


async def test_查無帳號_撤權同樣拒絕():
    """`assign` 為目標集覆寫，不區分提權 / 降權——查無帳號一律擋（比照 DP `_require_usable_target`）。"""
    svc = EtAssignService(accounts=_accounts(exists=False), audit=AsyncMock())

    with pytest.raises(AppError) as e:
        await svc.assign(_untouchable_db(), user_id="ghost", roles=set(), groups=set(), operator_id="adm")

    assert e.value.error_code == "ET_ROLE_004"


async def test_輸入檢核先於帳號查詢():
    """角色代碼無效時直接 422，不必多查一次帳號——檢核順序由便宜到貴。"""
    accounts = _accounts(exists=False)
    svc = EtAssignService(accounts=accounts, audit=AsyncMock())

    with pytest.raises(AppError) as e:
        await svc.assign(_untouchable_db(), user_id="ghost", roles={"SUPERUSER"}, groups=set(), operator_id="adm")

    assert e.value.error_code == "ET_ROLE_003"
    accounts.exists.assert_not_called()


async def test_帳號存在_放行至後續流程():
    """正向錨點：存在性檢核不得誤擋——放行後才會讀現況（替身 DB 於此被碰到即證明已通過）。"""
    svc = EtAssignService(accounts=_accounts(exists=True), audit=AsyncMock())

    with pytest.raises(AssertionError, match="讀取 DB"):
        await svc.assign(_untouchable_db(), user_id="u1", roles={ROLE_STUDENT}, groups=set(), operator_id="adm")


# ── AccountQueryService.exists ──────────────────────────────────────────────


def _query_service(status: AccountStatus | None) -> AccountQueryService:
    users = MagicMock()
    users.get_account_status = AsyncMock(return_value=status)
    return AccountQueryService(users=users)


async def test_exists_查無帳號回_false():
    assert await _query_service(None).exists(MagicMock(), "ghost") is False


async def test_exists_停用帳號仍算存在():
    """與 `is_usable` 之差別：存在性不看帳號狀態——停用 / 鎖定是 DP 另一道檢核的事。"""
    assert await _query_service(AccountStatus(status="DISABLED", locked_until=None)).exists(MagicMock(), "u1") is True
