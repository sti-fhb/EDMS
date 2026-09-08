"""common_seed_demo_accounts

Revision ID: 7b24b5dea3ad
Revises: db3214fd6543
Create Date: 2026-09-08 14:37:14.518094

建立 5 組示範測試帳號（含 DM / ET 角色）。

⚠️ **正式部署前請刪除本批帳號或更換密碼**——5 組帳號共用寫死於本檔的初始密碼，
任何跑過本 migration 的環境都能以該密碼登入。移除方式：`alembic downgrade` 至本版之前，
或於 DP 後台「使用者管理」停用 / 刪除 `*@edms.local` 帳號。

異動說明：
- 影響 Table：`DP_USER`（帳號主檔）、`DP_PWD_HIST`（密碼歷程 SEQ_NO=1）、
  `DM_USER_ROLE`、`ET_USER_ROLE`（角色指派）
- 不做任何 DDL，純資料 seed
- 以 `SEED_DEMO_ACCOUNTS`（預設 true）控制是否種入；**測試環境一律 false**——測試 DB
  同樣跑 `alembic upgrade head`，這批帳號會混進「列全部使用者 / 全部管理者 /
  DM_VIEWER 母體」等斷言的預期值（實測 7 條 integration 測試因此失敗）。
  注入點：`.github/workflows/ci.yml` 的 migration 步驟與
  `tests/integration/conftest.py` 的 `apply_migrations`。

角色配置（一次涵蓋 DM 4 角色與 ET 3 角色）：

| Email | 姓名 | DM 角色 | ET 角色 |
|-------|------|---------|---------|
| admin@edms.local | 示範管理者 | DM_ADMIN | ADMIN |
| editor@edms.local | 示範編輯者 | DM_EDITOR | STUDENT |
| reviewer@edms.local | 示範審核者 | DM_REVIEWER | STUDENT |
| teacher@edms.local | 示範教師 | DM_VIEWER | TEACHER |
| student@edms.local | 示範學員 | DM_VIEWER | STUDENT |

冪等性：
- `DP_USER` / `DP_PWD_HIST` 以 `ON CONFLICT DO NOTHING` 插入——**既有同 Email 帳號的密碼
  不會被覆寫**，僅補角色。重跑不會重設任何人的密碼。
- 角色以 `ON CONFLICT ... DO UPDATE SET "DELETED" = 0`（ET 另含 `IS_ACTIVE = true`）復原，
  曾被軟刪 / 停用的角色列可救回，避免重跑後角色靜默失效。

`DP_PWD_HIST` 補 `SEQ_NO = 1`：正常啟用流程會寫入首筆歷程，手動建帳號若不補，
使用者第一次改密碼的歷程會從第 2 筆起算、且防重用比對少一筆基準。
"""

import logging
from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op
from app.core.config import settings
from app.core.password_policy import hash_password

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "7b24b5dea3ad"
down_revision: Union[str, None] = "db3214fd6543"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

# 示範帳號共用初始密碼：13 字元、含大小寫 + 數字 + 特殊符號，
# 滿足特權帳號 12 字元門檻，管理者帳號日後自行改密碼時不會被強度檢核擋下。
# 刻意寫死——本批帳號僅供測試，正式環境請依檔頭警語移除。
_DEMO_PASSWORD = "Edms@Test2026"  # noqa: S105

# (USER_ID, EMAIL, USER_NAME, DM 角色, ET 角色)
_DEMO_ACCOUNTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("DEMOADMIN", "admin@edms.local", "示範管理者", "DM_ADMIN", "ADMIN"),
    ("DEMOEDITOR", "editor@edms.local", "示範編輯者", "DM_EDITOR", "STUDENT"),
    ("DEMOREVIEWER", "reviewer@edms.local", "示範審核者", "DM_REVIEWER", "STUDENT"),
    ("DEMOTEACHER", "teacher@edms.local", "示範教師", "DM_VIEWER", "TEACHER"),
    ("DEMOSTUDENT", "student@edms.local", "示範學員", "DM_VIEWER", "STUDENT"),
)

_INSERT_USER = text(
    'INSERT INTO "DP_USER" ('
    '"USER_ID", "EMAIL", "PWD_HASH", "USER_NAME", "STATUS", "LOGIN_FAIL_COUNT", '
    '"PWD_CHANGED_DATE", "MUST_CHANGE_PWD", "CREATED_USER", "CREATED_DATE", "DELETED"'
    ") VALUES (:uid, :email, :hash, :name, 'ACTIVE', 0, :now, false, :u, :now, 0) "
    'ON CONFLICT DO NOTHING RETURNING "USER_ID"'
)

# Email 於 Python 端已正規化為小寫；登入以精確比對查詢，大小寫不符會回「帳號或密碼錯誤」
_SELECT_USER_ID = text('SELECT "USER_ID" FROM "DP_USER" WHERE "EMAIL" = :email')

_INSERT_PWD_HIST = text(
    'INSERT INTO "DP_PWD_HIST" ("USER_ID", "SEQ_NO", "PWD_HASH", "CREATED_USER", "CREATED_DATE") '
    "VALUES (:uid, 1, :hash, :u, :now) ON CONFLICT DO NOTHING"
)

_UPSERT_DM_ROLE = text(
    'INSERT INTO "DM_USER_ROLE" ("USER_ID", "ROLE_CODE", "CREATED_USER", "CREATED_DATE", "DELETED") '
    "VALUES (:uid, :role, :u, :now, 0) "
    'ON CONFLICT ("USER_ID", "ROLE_CODE") DO UPDATE SET "DELETED" = 0'
)

_UPSERT_ET_ROLE = text(
    'INSERT INTO "ET_USER_ROLE" ("USER_ID", "ROLE", "IS_ACTIVE", "CREATED_USER", "CREATED_DATE", "DELETED") '
    "VALUES (:uid, :role, true, :u, :now, 0) "
    'ON CONFLICT ("USER_ID", "ROLE") DO UPDATE SET "DELETED" = 0, "IS_ACTIVE" = true'
)


def upgrade() -> None:
    # 測試環境（CI / 本機 pytest）設 SEED_DEMO_ACCOUNTS=false 略過：測試 DB 同樣跑
    # `alembic upgrade head`，這 5 個帳號會混進「列全部使用者 / 全部管理者 / DM_VIEWER
    # 母體」等斷言的預期值。schema 不受影響，僅不種資料。
    if not settings.SEED_DEMO_ACCOUNTS:
        logger.info("SEED_DEMO_ACCOUNTS=false，略過示範帳號 seed")
        return

    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for uid, email, name, dm_role, et_role in _DEMO_ACCOUNTS:
        normalized_email = email.strip().lower()
        pwd_hash = hash_password(_DEMO_PASSWORD)

        inserted_uid = conn.execute(
            _INSERT_USER,
            {"uid": uid, "email": normalized_email, "hash": pwd_hash, "name": name, "now": now, "u": _SEED_USER},
        ).scalar()

        if inserted_uid is not None:
            conn.execute(_INSERT_PWD_HIST, {"uid": inserted_uid, "hash": pwd_hash, "now": now, "u": _SEED_USER})
            target_uid = inserted_uid
        else:
            # 帳號已存在（同 Email 或同 USER_ID）：不動其密碼，僅補角色。
            # 以 Email 反查真實 USER_ID——既有帳號的 USER_ID 可能與本檔的固定值不同，
            # 直接沿用固定值會建出指不到任何帳號的孤兒角色列。
            target_uid = conn.execute(_SELECT_USER_ID, {"email": normalized_email}).scalar()
            if target_uid is None:
                continue

        conn.execute(_UPSERT_DM_ROLE, {"uid": target_uid, "role": dm_role, "now": now, "u": _SEED_USER})
        conn.execute(_UPSERT_ET_ROLE, {"uid": target_uid, "role": et_role, "now": now, "u": _SEED_USER})


def downgrade() -> None:
    """移除本 migration 所建之示範帳號與其角色、密碼歷程。

    僅刪 `CREATED_USER = 'SYSTEM'` 且 USER_ID 在本檔清單內的帳號——若某 Email 的帳號是
    本 migration 之外建立的（`ON CONFLICT DO NOTHING` 略過、只補了角色），其帳號與角色皆不動。

    刪除順序須先清 FK 指向 `DP_USER` 的兩張表（`DP_PWD_RESET` / `DP_PWD_HIST`），
    否則刪 `DP_USER` 會被外鍵擋下。
    """
    conn = op.get_bind()
    seed_ids = [row[0] for row in conn.execute(
        text('SELECT "USER_ID" FROM "DP_USER" WHERE "USER_ID" = ANY(:ids) AND "CREATED_USER" = :u'),
        {"ids": [acc[0] for acc in _DEMO_ACCOUNTS], "u": _SEED_USER},
    )]
    if not seed_ids:
        return

    for stmt in (
        'DELETE FROM "DM_USER_ROLE" WHERE "USER_ID" = ANY(:ids)',
        'DELETE FROM "ET_USER_ROLE" WHERE "USER_ID" = ANY(:ids)',
        'DELETE FROM "DP_PWD_RESET" WHERE "USER_ID" = ANY(:ids)',
        'DELETE FROM "DP_PWD_HIST" WHERE "USER_ID" = ANY(:ids)',
        'DELETE FROM "DP_USER" WHERE "USER_ID" = ANY(:ids)',
    ):
        conn.execute(text(stmt), {"ids": seed_ids})
