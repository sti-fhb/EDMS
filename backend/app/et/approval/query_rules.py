"""核可查詢之可見範圍（US17 / #385）——純函式，不碰 DB。

## SA Q1 裁示 C（2026-09-21）

教師（非管理者）查詢時依**結果**分流：

| 紀錄 | 教師可見範圍 |
|---|---|
| `RESULT = PASS` 且 `IS_REVOKED = false` | **全部課程** |
| `RESULT = FAIL` | 僅自己 owner 的課程 |
| `IS_REVOKED = true`（不論原 `RESULT`）| 僅自己 owner 的課程 |

管理者不受此分流（`FR-ET-US17-02`、場景 3）。

**為何不是「教師只能查自己的課」（選項 A）或「教師可查全部」（選項 B）**：客戶原始需求
是「用姓名查學員**通過**了哪些課程」——那天生跨課程（排班的人需要知道某人受訓完整
與否）。但「不通過」與其 `RESULT_NOTE`（如「實機操作需再加強」）是考核評價，不該讓
同儕教師隨意翻閱。C 讓兩者各歸各位。

⚠️ C 的已知缺點：教師看到某門課「沒出現」時，分不清是「還沒考」還是「考了沒過」。
故教師視角 MUST 常駐提示「不通過與已撤銷的紀錄僅顯示您所開設的課程」——**那句話是
本裁示的配套，不是可選的 UX 潤飾**。少了它，C 比 A 更容易誤導：A 至少整份清單範圍
一致，C 是兩種範圍混在同一張表裡。

## 🔴 為何回傳「條件」而不是「布林」

範圍判定必須進 SQL 的 `WHERE`。若改成「取出資料後在 Python 裡濾掉不該看的」，
`paginate()` 的 `meta.total` 算的是**過濾前**的筆數（它以同一個 `stmt` 產生 count），
每頁也會少於 `limit`——教師看到「共 40 筆」卻只翻得出 12 筆，而且不會有任何錯誤訊息。
"""

from sqlalchemy import and_, or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.et.approval.models import EtApproval
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse


def visible_clause(*, actor_id: str, is_admin: bool) -> ColumnElement[bool]:
    """教師 / 管理者查詢核可紀錄時的可見範圍條件（SA Q1 裁示 C）。

    Args:
        actor_id: 查詢者的 `USER_ID`，用於比對 `ET_COURSE.OWNER_ID`。
        is_admin: 是否具 ET 管理者角色。管理者不受任何範圍限制。

    Returns:
        可直接放進 `.where()` 的條件。**呼叫端的 SELECT 必須已 JOIN `ET_COURSE`**
        ——本條件會比對 `EtCourse.owner_id`，未 JOIN 會產生笛卡兒積而不是錯誤。

    ⚠️ 「通過」那一側**必須同時要求未撤銷**。被撤銷的通過其 `RESULT` 仍是 `PASS`，
    只依 `RESULT` 分流會讓它對全體教師可見**並顯示撤銷原因**——而撤銷原因正是負面判斷
    （誤植、考核有問題），那是本裁示要擋的東西從側門漏出去。
    """
    if is_admin:
        return true()
    return or_(
        and_(EtApproval.result == APPROVAL_PASS, EtApproval.is_revoked.is_(False)),
        EtCourse.owner_id == actor_id,
    )
