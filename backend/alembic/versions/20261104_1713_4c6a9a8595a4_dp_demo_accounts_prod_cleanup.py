"""dp_demo_accounts_prod_cleanup

Revision ID: 4c6a9a8595a4
Revises: b27739aa4ac6
Create Date: 2026-11-04 17:13:16.892218

上線前清理示範帳號：仍在用共用密碼的環境，刪除四組測試帳號、admin 設為首次登入強制變更密碼（#920）。

異動說明：
- 影響 Table：`DP_USER`（刪除 4 列或改為停用；admin 之 `MUST_CHANGE_PWD`），以及四組帳號在
  `DM_USER_ROLE`、`DM_USER_TAG`、`ET_USER_ROLE`、`ET_USER_TAG`、`ET_ENROLLMENT`、`DP_PWD_RESET`、
  `DP_PWD_HIST` 的列；不改 schema

## 以「密碼是否仍為 seed 雜湊」判定要不要動（比照 TBMS #5373）

`7b24b5dea3ad` 建立五組示範帳號，`18489e30023b` 把密碼換成寫死的雜湊（明文不進 repo）。
`PWD_HASH` **仍等於那五個雜湊值**＝密碼從未被改過＝仍是開發團隊共用的密碼，才處理；
改過密碼的環境一律不動。

| 環境 | 狀態 | 結果 |
|---|---|---|
| 院內正式機 | 尚未啟用，密碼未改 | 處理 |
| GCP 測試環境 | 2026-11-04 已改掉五組密碼（測試持續用到驗收） | 不動 |
| 開發者本機 dev 庫 | 未改 | 處理——要保留示範帳號的話，升級前先改密碼 |
| CI / 測試 DB | `SEED_DEMO_ACCOUNTS=false`，沒有這五組帳號 | 不動 |

不用環境變數判定：GCP 與正式機的設定幾乎相同，用旗標分辨容易設錯；密碼有沒有改過是直接的事實。

## 有業務資料的帳號改為停用、不刪除

帳號被其他表引用（建過課程、文件、作答、閱讀紀錄等）時，刪除會留下指向不存在帳號的資料——
那些表大多沒有外鍵，資料庫不會擋。故刪除前掃描**所有文字欄位**：

- `_DELETABLE`：隨帳號一併刪除（角色、標籤、選課、密碼 token / 歷程）
- `_KEPT_LOGS`：保留不刪的紀錄（稽核、寄信、排程、角色異動歷程）。`DP_AUDIT_LOG` 另有 trigger 禁止
  刪除；DP05 中這些紀錄的操作者改顯示 USER_ID
- 其餘任何引用 ⇒ 視為有業務資料，改 `STATUS = 'DISABLED'`（無法登入，資料關聯保留）

掃描採列舉資料庫實際欄位，而非手寫表名清單：日後新增的表也會被涵蓋，漏列只會讓帳號被停用而非刪除。

## admin 不刪

`admin@edms.local` 保留為院方起始管理者：設 `MUST_CHANGE_PWD = true`，首次登入即須變更密碼。
不動 `PWD_CHANGED_DATE`——改完密碼時系統會更新，90 天效期由此起算。

## downgrade

不還原：刪除的帳號無法復原，且還原共用密碼的帳號等於重新打開已關上的門。
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

#: 以 `USER_ID` 關聯、隨帳號一併刪除的表（先刪這些，最後才刪 `DP_USER`）
_DELETABLE: tuple[str, ...] = (
    "DM_USER_ROLE",
    "DM_USER_TAG",
    "ET_USER_ROLE",
    "ET_USER_TAG",
    "ET_ENROLLMENT",
    "DP_PWD_RESET",
    "DP_PWD_HIST",
)

#: 保留不刪、也不算業務資料的紀錄表
_KEPT_LOGS: frozenset[str] = frozenset({"DP_AUDIT_LOG", "DP_EMAIL_LOG", "DP_SCHEDULE_LOG", "DM_USER_ROLE_LOG"})

_SELECT_UNCHANGED = text(
    'SELECT "USER_ID", "PWD_HASH" FROM "DP_USER" WHERE "USER_ID" IN :uids AND "CREATED_USER" = :seed'
).bindparams(sa.bindparam("uids", expanding=True))

_TEXT_COLUMNS = text(
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema = current_schema() "
    "AND data_type IN ('character varying', 'character', 'text') "
    "ORDER BY table_name, column_name"
)

_FORCE_CHANGE = text(
    'UPDATE "DP_USER" SET "MUST_CHANGE_PWD" = true, "UPDATED_USER" = :u, "UPDATED_DATE" = :now WHERE "USER_ID" = :uid'
)

_DISABLE = text(
    'UPDATE "DP_USER" SET "STATUS" = :status, "UPDATED_USER" = :u, "UPDATED_DATE" = :now WHERE "USER_ID" = :uid'
)


def _text_columns(conn: sa.Connection) -> dict[str, list[str]]:
    """{表名: [文字欄位, ...]}——掃描引用的範圍。"""
    columns: dict[str, list[str]] = {}
    for table_name, column_name in conn.execute(_TEXT_COLUMNS):
        columns.setdefault(table_name, []).append(column_name)
    return columns


def _has_business_refs(conn: sa.Connection, uid: str, columns: dict[str, list[str]]) -> bool:
    """帳號是否被 `_DELETABLE` / `_KEPT_LOGS` 以外的資料引用。

    `DP_USER` 與 `_DELETABLE` 只看「別人的列」引用到本帳號（本帳號自己的列會一併刪除）。
    以 SQLAlchemy Core 組查詢：表名、欄位名由 `sa.table` / `sa.column` 自動加引號，不拼接 SQL 字串。
    """
    for table_name, names in columns.items():
        if table_name in _KEPT_LOGS:
            continue
        own_rows_go_away = table_name == "DP_USER" or table_name in _DELETABLE
        tbl = sa.table(table_name, *(sa.column(n) for n in {*names, "USER_ID"}))
        refs = sa.or_(*(tbl.c[n] == uid for n in names))
        if own_rows_go_away:
            refs = sa.and_(refs, tbl.c.USER_ID != uid)
        if conn.execute(sa.select(sa.func.count()).select_from(tbl).where(refs)).scalar():
            return True
    return False


def _delete_account(conn: sa.Connection, uid: str) -> None:
    for table_name in (*_DELETABLE, "DP_USER"):
        tbl = sa.table(table_name, sa.column("USER_ID"))
        conn.execute(sa.delete(tbl).where(tbl.c.USER_ID == uid))


def upgrade() -> None:
    conn = op.get_bind()
    unchanged = [
        uid
        for uid, pwd_hash in conn.execute(_SELECT_UNCHANGED, {"uids": list(_SEED_HASHES), "seed": _SEED_USER})
        if pwd_hash == _SEED_HASHES[uid]
    ]
    if not unchanged:
        return

    columns = _text_columns(conn)
    now = datetime.now(timezone.utc)
    for uid in unchanged:
        if uid == _ADMIN:
            conn.execute(_FORCE_CHANGE, {"uid": uid, "u": _SEED_USER, "now": now})
        elif _has_business_refs(conn, uid, columns):
            conn.execute(_DISABLE, {"uid": uid, "u": _SEED_USER, "now": now, "status": "DISABLED"})
        else:
            _delete_account(conn, uid)


def downgrade() -> None:
    """不還原：刪除的帳號無法復原，還原共用密碼的帳號等於重新打開已關上的門。"""
