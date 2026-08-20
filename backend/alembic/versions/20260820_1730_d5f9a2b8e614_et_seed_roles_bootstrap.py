"""et_seed_roles_bootstrap

Revision ID: d5f9a2b8e614
Revises: c4e8f1a6d372
Create Date: 2026-08-20 17:30:00.000000

ET 角色 bootstrap（#185 T024，依 SA Q1 裁示）——兩件事：

## 1. 首位 ET 管理者（解開 bootstrap 死結）

`dp/roles/service.py` 之 `_require_manageable()` 會呼叫
`module_admin_gate.is_module_admin("ET", ...)`，而該閘為 **fail-closed**。
`ET_USER_ROLE` 初始為空 → 無人是 ET 管理者 → 任何人呼叫 `assign` 皆被 403
`DP_ROLE_001` 擋下 → **沒有人能授予第一個 ET 管理者角色**。

本 migration 依 `.env` 之 `ET_BOOTSTRAP_ADMIN_EMAIL` 查 `DP_USER` 取 `USER_ID` 後
授予 `ADMIN`，解開死結。此後所有 ET 角色皆可由該管理者於 DP 後台「權限管理」指派。

**未設定或查無帳號 → 跳過並記 log，不使 migration 失敗**——CI 與新環境無此設定亦
須能正常升級。

> 註：`DP_USER` 之讀取為**唯讀 JOIN**，已列於 et/spec.md §外模組 table 引用清單
> （A 類白名單）。本 migration **不寫入 `DP_USER`**——帳號由平台建立。

## 2. 存量帳號回填「學員」角色

`grant_default_student_role`（SRVET002）僅於 `dp/user/activation.py` 之**帳號啟用當下**
觸發，ET 上線前既有的帳號不會回頭補——它們在 `ET_USER_ROLE` 為空，一進 ET 就被存取閘
403 `ET_AUTH_001` 擋下。

「學員」為 spec 設計上的**預設角色**（人人皆有），存量帳號沒有只是因為 hook 上線得晚、
非業務上要阻擋，故一併回填。帳號狀態（停用 / 鎖定）**不納入判斷**——角色指派與帳號
狀態為兩件事，帳號狀態由 DP 於登入時把關。

但**已軟刪除之帳號（`DP_USER.DELETED = 1`）一律排除**：那些帳號不會再登入，回填只會
在 ET 側留下永不使用的幽靈角色列，污染日後之使用者清單與稽核資料。與「停用 / 鎖定」
不同——後者是暫時狀態、帳號仍存在。

冪等：兩者皆以 `WHERE NOT EXISTS` 判重，重跑不重複。
"""

import logging
from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op
from app.core.config import settings

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "d5f9a2b8e614"
down_revision: Union[str, None] = "c4e8f1a6d372"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_ROLE_ADMIN = "ADMIN"
_ROLE_STUDENT = "STUDENT"


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # ── 1. 存量帳號回填學員角色 ────────────────────────────────────────────
    # 以單一 INSERT ... SELECT 完成，避免逐筆往返；WHERE NOT EXISTS 確保冪等。
    # 同一參數不可同時出現在 SELECT 值與 WHERE 比較位置——asyncpg 會因無法推導一致
    # 型別而拋 AmbiguousParameterError。故拆為 role_val / role_chk 兩個綁定名
    # （比照 dm_seed_business_data 之 name_val / name_chk 寫法）。
    result = conn.execute(
        text(
            'INSERT INTO "ET_USER_ROLE" ("USER_ID", "ROLE", "IS_ACTIVE", "CREATED_USER", "CREATED_DATE", "DELETED") '
            'SELECT u."USER_ID", :role_val, true, :u, :d, 0 FROM "DP_USER" u '
            'WHERE u."DELETED" = 0 '
            'AND NOT EXISTS (SELECT 1 FROM "ET_USER_ROLE" r '
            'WHERE r."USER_ID" = u."USER_ID" AND r."ROLE" = :role_chk)'
        ),
        {"role_val": _ROLE_STUDENT, "role_chk": _ROLE_STUDENT, "u": _SEED_USER, "d": now},
    )
    logger.info("ET bootstrap：存量帳號回填學員角色 %s 筆", result.rowcount)

    # ── 2. 首位 ET 管理者 ──────────────────────────────────────────────────
    admin_email = (settings.ET_BOOTSTRAP_ADMIN_EMAIL or "").strip()
    if not admin_email:
        logger.warning(
            "ET bootstrap：未設定 ET_BOOTSTRAP_ADMIN_EMAIL，略過首位管理者授予。"
            "在有人取得 ET 管理者角色前，DP 後台無法指派 ET 角色（fail-closed）。"
        )
        return

    # Email 比對採小寫正規化，對齊平台 US1/US2 之 email 正規化慣例（#35）
    user_id = conn.execute(
        text(
            'SELECT "USER_ID" FROM "DP_USER" '
            'WHERE lower("EMAIL") = lower(:e) AND "DELETED" = 0 AND "STATUS" = \'ACTIVE\''
        ),
        {"e": admin_email},
    ).scalar()

    if user_id is None:
        logger.warning(
            "ET bootstrap：ET_BOOTSTRAP_ADMIN_EMAIL 所指帳號不存在於 DP_USER，略過首位管理者授予。"
            "請確認該帳號已建立後，重新執行本 migration 或手動授予。"
        )
        return

    conn.execute(
        text(
            'INSERT INTO "ET_USER_ROLE" ("USER_ID", "ROLE", "IS_ACTIVE", "CREATED_USER", "CREATED_DATE", "DELETED") '
            "SELECT :uid_val, :role_val, true, :u, :d, 0 "
            'WHERE NOT EXISTS (SELECT 1 FROM "ET_USER_ROLE" '
            'WHERE "USER_ID" = :uid_chk AND "ROLE" = :role_chk)'
        ),
        {
            "uid_val": user_id,
            "uid_chk": user_id,
            "role_val": _ROLE_ADMIN,
            "role_chk": _ROLE_ADMIN,
            "u": _SEED_USER,
            "d": now,
        },
    )
    logger.info("ET bootstrap：已授予首位管理者角色（USER_ID=%s）", user_id)


def downgrade() -> None:
    """刪除 `CREATED_USER='SYSTEM'` 之 STUDENT / ADMIN 列。

    管理者後續於 DP 後台指派之角色不受影響（那些列之 `CREATED_USER` 為操作者 USER_ID）。

    ⚠️ **範圍略大於本 migration 所種**：`grant_default_student_role` 於帳號啟用時建立的列
    `CREATED_USER` 同樣是 `SYSTEM`，故會一併刪除。實務上可自癒（下次 upgrade 會回填、
    或下次帳號啟用會重新授予），但降級後至再升級之間，該期間新建帳號需重新登入才會補上。
    """
    conn = op.get_bind()
    conn.execute(
        text('DELETE FROM "ET_USER_ROLE" WHERE "CREATED_USER" = :u AND "ROLE" = ANY(:roles)'),
        {"u": _SEED_USER, "roles": [_ROLE_STUDENT, _ROLE_ADMIN]},
    )
