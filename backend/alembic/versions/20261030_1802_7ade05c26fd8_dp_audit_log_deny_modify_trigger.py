"""dp_audit_log_deny_modify_trigger

Revision ID: 7ade05c26fd8
Revises: 04fc1cf07681
Create Date: 2026-10-30 18:02:38.597037

DP_AUDIT_LOG 加 trigger，拒絕 UPDATE / DELETE / TRUNCATE（#22）。

異動說明：
- 影響 Table：DP_AUDIT_LOG（不改欄位，只加 trigger 與其函式）
- 新增函式 FN_DP_AUDIT_LOG_DENY_MODIFY、trigger TRG_DP_AUDIT_LOG_DENY_MODIFY
  （BEFORE UPDATE OR DELETE OR TRUNCATE，FOR EACH STATEMENT）

## 與 app 執行期角色的分工

#22 的兩層防護各管一件事：

| 層 | 落點 | 擋誰 |
|---|---|---|
| GRANT（只給 INSERT / SELECT） | `scripts/db-app-role.sql`（部署層，刻意不放 migration） | app 執行期角色 |
| 本 trigger | 本 migration（schema 物件） | 所有連線，含資料表 owner 與 superuser 的一般 DML |

trigger 是縱深防禦：GRANT 設錯時，一般 DML 仍改不動稽核表。它擋不住具 owner / superuser 權限者
停用 trigger——特權帳號的防護屬於特權操作稽核與外部錨定的範圍，歸 T011（見 issue #22「不在本 issue」）。

⚠️ 日後若有 migration 重建或分割（partition）本表，須一併重建本 trigger（statement 層級 trigger 不會
套用到 partition），並以 owner 重跑 `scripts/db-app-role.sql`。

## FOR EACH STATEMENT 的理由

TRUNCATE 只有 statement 層級 trigger 會觸發；UPDATE / DELETE 一併用 statement 層級，
一個 trigger 涵蓋三種操作。代價是「條件命中 0 列」的 UPDATE / DELETE 也會報錯——
本表本來就不允許任何改刪，沒有合法的 0 列情境。

## 日後若真的需要改稽核表

（例如資料修補 migration）須在**同一交易**內先 `DISABLE TRIGGER`、做完再 `ENABLE TRIGGER`，
並在該 migration docstring 說明理由。這是刻意留下的摩擦，不要改成預設停用。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "7ade05c26fd8"
down_revision: Union[str, None] = "04fc1cf07681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION "FN_DP_AUDIT_LOG_DENY_MODIFY"() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'DP_AUDIT_LOG 為 append-only，不允許 %', TG_OP;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER "TRG_DP_AUDIT_LOG_DENY_MODIFY"
        BEFORE UPDATE OR DELETE OR TRUNCATE ON "DP_AUDIT_LOG"
        FOR EACH STATEMENT EXECUTE FUNCTION "FN_DP_AUDIT_LOG_DENY_MODIFY"()
        """
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS "TRG_DP_AUDIT_LOG_DENY_MODIFY" ON "DP_AUDIT_LOG"')
    op.execute('DROP FUNCTION IF EXISTS "FN_DP_AUDIT_LOG_DENY_MODIFY"()')
