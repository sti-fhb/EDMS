"""帳號可用性判定（#250）。

「帳號可用」＝`STATUS='ACTIVE'` 且不在鎖定中（`LOCKED_UNTIL` 為空或已逾時）。此判定於
#250 有三個使用點——DP 角色指派檢核、DM 指定審核者下拉、前端列灰化——故集中於此，
避免三份各自漂移。`STATUS` 值域（ACTIVE / DISABLED）屬 DP 語意，其他模組不得自行解讀，
需要 SQL 條件者請取用 `account_usable_clause()`。

⚠️ 鎖定必須比對**當下時間**：逾時的 `LOCKED_UNTIL` 會留在欄位裡（登入時才清），
以 `IS NOT NULL` 判定會讓早已自動解鎖的帳號永遠被當成不可用。
"""

from datetime import datetime
from typing import NamedTuple, Optional

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.dp.users.models import DpUser

_STATUS_ACTIVE = "ACTIVE"


class AccountStatus(NamedTuple):
    """帳號狀態兩維度（供跨子模組傳遞，不洩漏 ORM model）。"""

    status: str
    locked_until: Optional[datetime]


def is_account_usable(*, status: str, locked_until: Optional[datetime], now: datetime) -> bool:
    """帳號目前是否可用（未停用且未在鎖定中）。

    取欄位值而非 model 實例，使 `DpUser`（ORM）與 `UserResponse`（Pydantic）兩種來源皆可呼叫。

    Args:
        status: `DP_USER.STATUS` 原始值（ACTIVE / DISABLED）。
        locked_until: 鎖定截止時間；None 表未曾鎖定。
        now: 判定基準時間（aware），由呼叫端以 `utcnow()` 取得。

    Returns:
        可用回 True；停用、鎖定未逾時、或狀態非 ACTIVE（fail-closed）回 False。
    """
    if status != _STATUS_ACTIVE:
        return False
    return locked_until is None or locked_until <= now


def account_usable_clause(now: datetime) -> ColumnElement[bool]:
    """「帳號可用」之 SQL 條件，供 `select().where()` 掛載。

    與 `is_account_usable` 同一界線（`<= now` 視為已解鎖），亦與 dp-users 列表
    `status="active"` 篩選（repository.build_list_stmt）一致。

    Args:
        now: 判定基準時間（aware）。

    Returns:
        可掛進 where 的布林條件。
    """
    return and_(
        DpUser.status == _STATUS_ACTIVE,
        or_(DpUser.locked_until.is_(None), DpUser.locked_until <= now),
    )
