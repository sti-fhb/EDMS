"""「可被指定為審核者」之清單查詢（#250）。

條件：具 `DM_REVIEWER` 角色（DM 自持）**且** `DP_USER` 帳號可用（未停用、未鎖定中）。
唯一使用者為 `dm/editor/repository.list_reviewers`——送簽表單的審核者下拉。

**僅供顯示用途**：JOIN `DP_USER` 屬 `sti-backend-boundaries.md` §報表/查詢類唯讀例外，
且帳號可用性條件取自 DP 的 `account_usable_clause`（不在此重新實作 DP 的業務規則）。

⚠️ 送簽時的伺服器端檢核**不走這裡**：該處查詢結果會成為寫入的判斷依據，依邊界規則
不適用唯讀例外，改由 `dm/review/service._ensure_assignable_reviewer` 以
`services.AccountQueryService`（DP 出口）判定帳號、自查 `DM_USER_ROLE` 判定角色。
兩邊判準必須一致（下拉給什麼、送簽就只接受什麼），由 `test_dm_editor_reviewers.py`
的下拉排除案例與送簽拒絕案例共同把關——改動任一側時請同步檢視另一側。
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
