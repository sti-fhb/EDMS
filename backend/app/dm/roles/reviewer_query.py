"""「可被指定為審核者」之單一查詢定義（#250）。

條件：具 `DM_REVIEWER` 角色（DM 自持）**且** `DP_USER` 帳號可用（未停用、未鎖定中）。

兩處共用同一定義，避免判準漂移——**下拉給什麼，送簽就只接受什麼**：
- `dm/editor/repository.list_reviewers`：送簽表單的審核者下拉清單
- `dm/review/service.submit`：送簽時的伺服器端檢核（擋直接打 API 繞過下拉）

帳號可用性條件取自 DP 的 `account_usable_clause`（`DP_USER.STATUS` 值域屬 DP 語意，
DM 不自行解讀）。JOIN `DP_USER` 為唯讀查詢，屬 `sti-backend-boundaries.md`
§報表/查詢類唯讀例外；不在此重新實作 DP 的業務規則。
"""

from datetime import datetime

from sqlalchemy import Select, select

from app.dm.roles.authz import DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.account_status import account_usable_clause
from app.dp.users.models import DpUser


def assignable_reviewers_stmt(now: datetime) -> Select:
    """可被指定為審核者之使用者查詢（回 USER_ID / USER_NAME 兩欄，未排序）。

    呼叫端自行加上排除自己、排序、或單筆比對等條件。

    Args:
        now: 鎖定逾時判定基準（aware）。

    Returns:
        `Select`，欄位為 (USER_ID, USER_NAME)。
    """
    return (
        select(DpUser.user_id, DpUser.user_name)
        .join(DmUserRole, DmUserRole.user_id == DpUser.user_id)
        .where(
            DmUserRole.role_code == DM_REVIEWER,
            DmUserRole.deleted == 0,
            DpUser.deleted == 0,
            account_usable_clause(now),
        )
    )
