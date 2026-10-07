"""dp_seed_action_type_query

Revision ID: c7d2e4f9a8b1
Revises: b4e7c9a1d2f3
Create Date: 2026-10-07 10:30:00.000000

ACTION_TYPE 清單補 QUERY（#548）。

異動說明：
- 影響 Table：`DP_PARAM_D`（新增 1 列，不改 schema）
- `ACTION_TYPE` 原有 6 列（LOGIN / LOGOUT / CREATE / UPDATE / DELETE / EXPORT），
  補第 7 列 `QUERY`

## 為何需要一個讀取類的 ACTION_TYPE

#548 移除了 ET04 核可查詢的「至少給一個條件」與課程擁有權兩道閘，於是「不指名地
一次取回全系統核可紀錄」成為合法操作。母體限制沒有了之後，**防列舉只剩角色受控**，
事後追責因此成為必要——不能出現「能全量取回但零軌跡」的空窗期。

既有六個值沒有一個適合：`EXPORT` 語意是「產生檔案帶走」（ET 週報明細、ET02 學員清單），
ET04 的查詢不產生檔案；借用它會污染 DP06 的「匯出」篩選，日後問「誰匯出過東西」
會撈到一堆查詢事件。

⚠️ **新增 ACTION_TYPE 要改三處**，`dp/audit/router.py` 的註解列了這張清單，而且記錄了
它被漏過一次（`EXPORT` 於 #322 導入時只補了 label，漏了 `_Action` 值域與本種子清單，
直到 #477 才發現，症狀是「下拉選得到、查詢回 422」）：

1. `dp/audit/query_service._ACTION_LABELS`（`ACTION_OPTIONS` 由它推導）
2. `dp/audit/router._Action` 的 `Literal` 值域
3. **本 migration**

⚠️ **`EDIT_SCOPE` 必填**：#450 起該欄為 NOT NULL 且刻意不設 `server_default`，裸 SQL
INSERT 不帶此欄會直接違反約束。值取 `HIDDEN`，與同組其餘六列一致（由 #171 的
`_HIDDEN_MASTERS` 整組填入）——不一致的話維護頁會冒出一個其餘同組成員都看不到的孤兒列。

⚠️ **不能從 DP03 畫面新增**：`ACTION_TYPE` 同時被 `service._SYSTEM_PARAM_IDS` 擋在維護
面外（主檔層 404）且全列 `HIDDEN`，所以只能走 migration。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "c7d2e4f9a8b1"
down_revision: Union[str, None] = "b4e7c9a1d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PARAM_ID = "ACTION_TYPE"
_PARAM_KEY = "QUERY"


def upgrade() -> None:
    conn = op.get_bind()
    # 既存則跳過：本 migration 可能在已手動補過的環境重跑（sti-alembic-rules §Seed Data）。
    # SQL 本體靜態；會變動的值一律具名綁定，`SYSTEM` / `now()` / 旗標為靜態字面量。
    conn.execute(
        text(
            'INSERT INTO "DP_PARAM_D" '
            '("PARAM_ID", "PARAM_KEY", "PARAM_NAME", "PARAM_VALUE", "DESCRIPTION", '
            '"SORT_ORDER", "IS_ENABLED", "EDIT_SCOPE", "CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:param_id, :param_key, :param_name, NULL, :description, "
            ":sort_order, true, :edit_scope, 'SYSTEM', now(), 0) "
            'ON CONFLICT ("PARAM_ID", "PARAM_KEY") DO NOTHING'
        ).bindparams(
            param_id=_PARAM_ID,
            param_key=_PARAM_KEY,
            param_name="查詢",  # 與 query_service._ACTION_LABELS 一致（前端經 /options 取得，不另維護）
            description="不指名條件之大量讀取（ET04 核可查詢未給關鍵字時）",
            sort_order=7,  # 接在既有六列（1~6）之後
            edit_scope="HIDDEN",  # 見 docstring：與同組其餘六列一致
        )
    )


def downgrade() -> None:
    """移除本 migration 新增的那一列。

    硬刪而非軟刪：`ACTION_TYPE` 是程式碼寫死的 enum 清單、非業務資料，留一列
    `DELETED=1` 的殘骸沒有意義，且 `get_param_list()` 本就濾掉軟刪列、留著也查不到。
    條件帶 `CREATED_USER='SYSTEM'`，不誤刪人為補建的同鍵列。

    ⚠️ **不刪已寫入的 `DP_AUDIT_LOG` 列**：那是 append-only 的鏈式稽核，刪除會毀鏈。
    降版後既有的 `QUERY` 事件仍在表中，只是在 DP06 的下拉裡選不到、label 退回原碼
    （`labelOf` 查不到時回原碼，不是空字串）。
    """
    op.get_bind().execute(
        text(
            'DELETE FROM "DP_PARAM_D" '
            'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key AND "CREATED_USER" = \'SYSTEM\''
        ).bindparams(param_id=_PARAM_ID, param_key=_PARAM_KEY)
    )
