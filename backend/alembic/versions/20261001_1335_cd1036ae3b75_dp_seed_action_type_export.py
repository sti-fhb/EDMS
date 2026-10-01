"""dp_seed_action_type_export

Revision ID: cd1036ae3b75
Revises: 381f643aefb4
Create Date: 2026-10-01 13:35:00.000000

ACTION_TYPE 清單補 EXPORT（#477）。

異動說明：
- 影響 Table：`DP_PARAM_D`（新增 1 列，不改 schema）
- `ACTION_TYPE` 原有 5 列（LOGIN / LOGOUT / CREATE / UPDATE / DELETE），補第 6 列 `EXPORT`

`EXPORT` 於 #322 導入（SA 裁示 2026-09-14），當時補了 `query_service._ACTION_LABELS` 與
前端 `auditLabels.ts` 兩處 label，但**漏了這份種子清單與 router 的 `_Action` 值域**，
導致「操作類別」下拉選得到「匯出」、查詢卻被擋成 422（#477 缺陷 2）。

⚠️ **`EDIT_SCOPE` 必填**：#450 起該欄為 NOT NULL 且刻意不設 `server_default`，裸 SQL INSERT
不帶此欄會直接違反約束。值取 `HIDDEN`——`ACTION_TYPE` 五列由 **#171（`71ca59c07bd1`）的 `_HIDDEN_MASTERS`** 整組填入；
⚠️ **不是 #459**，那支只處理 9 列 READONLY，其 `_TARGETS` 不含 `ACTION_TYPE`（該檔註解有特別
澄清這點）。新列若不一致，維護頁會冒出一個其餘同組成員都看不到的孤兒列。

⚠️ **不能從 DP03 畫面新增**：`ACTION_TYPE` 同時被 `service._SYSTEM_PARAM_IDS` 擋在維護面外
（主檔層 404）且全列 `HIDDEN`，所以只能走 migration。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "cd1036ae3b75"
down_revision: Union[str, None] = "381f643aefb4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PARAM_ID = "ACTION_TYPE"
_PARAM_KEY = "EXPORT"


def upgrade() -> None:
    conn = op.get_bind()
    # 既存則跳過：本 migration 可能在已手動補過的環境重跑（sti-alembic-rules §Seed Data）。
    # SQL 本體靜態；**會變動的值**一律具名綁定，`SYSTEM` / `now()` / 旗標為靜態字面量。
    # （不寫成「值一律具名綁定」——那比實際做到的強，照抄的人會以為內嵌字面量也被涵蓋。）
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
            param_name="匯出",  # 與 query_service._ACTION_LABELS 一致（前端經 /options 取得，不另維護）
            description="具名個資或大量資料之匯出（ET 週報明細、ET02 學員清單與問卷結果）",
            sort_order=6,  # 接在既有五列（1~5）之後
            edit_scope="HIDDEN",  # 見 docstring：與同組其餘五列一致
        )
    )


def downgrade() -> None:
    """移除本 migration 新增的那一列。

    硬刪而非軟刪：`ACTION_TYPE` 是程式碼寫死的 enum 清單、非業務資料，留一列
    `DELETED=1` 的殘骸沒有意義，且 `get_param_list()` 本就濾掉軟刪列、留著也查不到。
    條件帶 `CREATED_USER='SYSTEM'`，不誤刪人為補建的同鍵列。
    """
    op.get_bind().execute(
        text(
            'DELETE FROM "DP_PARAM_D" '
            'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key AND "CREATED_USER" = \'SYSTEM\''
        ).bindparams(param_id=_PARAM_ID, param_key=_PARAM_KEY)
    )
