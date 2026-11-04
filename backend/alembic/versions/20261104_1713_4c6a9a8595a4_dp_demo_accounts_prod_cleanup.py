"""dp_demo_accounts_prod_cleanup

Revision ID: 4c6a9a8595a4
Revises: b27739aa4ac6
Create Date: 2026-11-04 17:13:16.892218

上線前處置示範帳號：仍在用共用密碼者一律標為須變更密碼，admin 以外四組並停用（#922）。

異動說明：
- 影響 Table：`DP_USER`（至多 5 列之 `MUST_CHANGE_PWD`、`STATUS`、`UPDATED_*`），不改 schema

## 以「密碼是否仍為 seed 雜湊」判定要不要動（比照 TBMS #5373）

`7b24b5dea3ad` 建立五組示範帳號，`18489e30023b` 把密碼換成寫死的雜湊（明文不進 repo）。
`PWD_HASH` **仍等於那五個雜湊值**＝密碼從未被改過＝仍是開發團隊共用的密碼，才處理；
改過密碼的帳號一律不動。逐帳號判斷，不是逐環境。

| 環境 | 狀態 | 結果 |
|---|---|---|
| 院內正式機 | 尚未啟用，密碼未改 | 處理 |
| GCP 測試環境 | 2026-11-04 已改掉五組密碼（測試持續用到驗收） | 不動 |
| 開發者本機 dev 庫 | 未改 | 處理——要保留示範帳號的話，升級前先改密碼 |
| CI / 測試 DB | `SEED_DEMO_ACCOUNTS=false`，沒有這五組帳號 | 不動 |

不用環境變數判定：GCP 與正式機的設定幾乎相同，用旗標分辨容易設錯；密碼有沒有改過是直接的事實。

## 處置

| 帳號 | `MUST_CHANGE_PWD` | `STATUS` | 理由 |
|---|---|---|---|
| `DEMOADMIN` | true | 不動（ACTIVE） | 院方起始管理者：首次登入即須改掉共用密碼 |
| 其餘四組 | true | `DISABLED` | 測試帳號不得登入；日後若被重新啟用，首次登入仍須改密碼 |

停用而非刪除：帳號被稽核紀錄、角色等資料引用，刪除會留下指向不存在帳號的資料；停用即無法登入，
資料關聯完整保留。四組也標 `MUST_CHANGE_PWD`，是因為 DP02 重新啟用只改 `STATUS`、不清此旗標——
不標的話，被重新啟用的帳號會帶著公開過的共用密碼直接可用（TBMS #5373 對停用中的 `changeme`
帳號同樣標為過期，理由相同）。

不動 `PWD_CHANGED_DATE`：改完密碼時系統會更新，90 天效期由此起算。

## downgrade

不還原：還原等於讓共用密碼的帳號重新可用、免改密碼。
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "4c6a9a8595a4"
down_revision: Union[str, None] = "b27739aa4ac6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_ADMIN = "DEMOADMIN"

#: 同 `18489e30023b._HASHES`（複製而非 import：已合併的 migration 不應被其他 migration 依賴）
_SEED_HASHES: dict[str, str] = {
    "DEMOADMIN": "$2b$12$fHO3qY.YIF9uLeC8XZFjHO8SdiWV2BjvS78Ke3sLtjAgKRXRuiYr.",
    "DEMOEDITOR": "$2b$12$0KUQklhGFLGONHpbYTcxLOYti.U2bQYJN9Xpjw83Ye8Va21Dq2Hvu",
    "DEMOREVIEWER": "$2b$12$ZS0yr3F3IU4zxm7DBf5VIe4emhCDlCnBhI5bfJMxGZJ0Zprvg5uYm",
    "DEMOTEACHER": "$2b$12$kxTcvwDlnmcmd6fE3JOTBeKieIkAhUZD1aS/Pv6tOz7yIzSdK0bIq",
    "DEMOSTUDENT": "$2b$12$gksvK8ZCNDRxYOkQdC.DAe2NqzorRP5vxbYuyEgH1x6N6cm5TDwDm",
}

_SELECT_SEEDED = text(
    'SELECT "USER_ID", "PWD_HASH" FROM "DP_USER" WHERE "USER_ID" IN :uids AND "CREATED_USER" = :seed'
).bindparams(sa.bindparam("uids", expanding=True))

_FORCE_CHANGE = text(
    'UPDATE "DP_USER" SET "MUST_CHANGE_PWD" = true, "UPDATED_USER" = :u, "UPDATED_DATE" = :now WHERE "USER_ID" = :uid'
)

_FORCE_CHANGE_AND_DISABLE = text(
    'UPDATE "DP_USER" SET "MUST_CHANGE_PWD" = true, "STATUS" = :status, "UPDATED_USER" = :u, "UPDATED_DATE" = :now '
    'WHERE "USER_ID" = :uid'
)


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = conn.execute(_SELECT_SEEDED, {"uids": list(_SEED_HASHES), "seed": _SEED_USER})
    for uid, pwd_hash in rows.all():
        if pwd_hash != _SEED_HASHES[uid]:
            continue  # 密碼已改過：不再是共用密碼，不動
        if uid == _ADMIN:
            conn.execute(_FORCE_CHANGE, {"uid": uid, "u": _SEED_USER, "now": now})
        else:
            conn.execute(_FORCE_CHANGE_AND_DISABLE, {"uid": uid, "u": _SEED_USER, "now": now, "status": "DISABLED"})


def downgrade() -> None:
    """不還原：還原等於讓共用密碼的帳號重新可用、免改密碼。"""
