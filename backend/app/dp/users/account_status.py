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


def is_account_disabled(status: str) -> bool:
    """帳號是否已停用（`STATUS` 非 `ACTIVE`）。

    ## 與 `is_account_usable` 的差別：**不看鎖定**

    鎖定是暫時的、會自動解除；停用是管理者（或 SCHDP001 閒置 90 天）的決定，在有人改
    回來之前一直有效。ET 的課程擁有者標記要的是後者——把連續登入失敗而被鎖 15 分鐘的
    教師標成「已停用帳號」是錯的。

    ## 為何放在 DP

    本模組 docstring 明訂「`STATUS` 值域屬 DP 語意，其他模組不得自行解讀」。ET05 課程
    清單需要判定擁有者是否停用（#330），若在 ET 那側寫 `status == "DISABLED"`，DP 日後
    新增第三種狀態時 ET 會靜默地把它算成「未停用」。

    Args:
        status: `DP_USER.STATUS` 原始值。

    Returns:
        非 `ACTIVE` 一律視為停用（fail-closed，與 `is_account_usable` 同一立場）。
    """
    return status != _STATUS_ACTIVE


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


def account_not_disabled_clause() -> ColumnElement[bool]:
    """「帳號未停用」之 SQL 條件（**不看鎖定**），供 `select().where()` 掛載。

    `is_account_disabled` 的 SQL 對應，補上本模組原本缺的那一半——Python 側有
    `is_account_usable` / `is_account_disabled` 一對，SQL 側原本只有
    `account_usable_clause`，於是需要「未停用但容許鎖定中」的查詢無處可取，只能自己
    寫 `status == "ACTIVE"`，正是本模組 docstring 禁止的「其他模組自行解讀」。

    ## 何時用這支、何時用 `account_usable_clause`

    問「這個人現在要不要做什麼動作」——用 `account_usable_clause`（鎖定中的人此刻
    進不來）。問「這個人還是不是這裡的人」——用本函式：鎖定是暫時的、會自動解除，
    被鎖 15 分鐘的同仁明天照樣要收到文件發布通知（同
    `review/center_service` 催辦跳過判定的推理）。

    Returns:
        可掛進 where 的布林條件；非 `ACTIVE` 一律視為停用（fail-closed）。
    """
    return DpUser.status == _STATUS_ACTIVE
