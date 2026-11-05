"""dp_seed_vendor_ops_account

Revision ID: 36af0d3943bf
Revises: 4c6a9a8595a4
Create Date: 2026-11-05 15:23:59.251723

建立廠商維運專用的管理員帳號 `edmsops`（#927）。

院內交付後系統管理權交由院方；院方若更換管理員密碼，廠商即無法登入維運。本帳號具全部
功能權限，並由程式保護：不可停用、不可經使用者管理改名、不可拿掉預設角色、不被閒置停用
排程停用（判斷依據為固定的 USER_ID，見 `app/core/ops_account.py`）。

異動說明：
- 影響 Table：`DP_USER`、`DP_PWD_HIST`（SEQ_NO=1）、`DM_USER_ROLE`（ADMIN / EDITOR / REVIEWER 三角色）、`ET_USER_ROLE`（ADMIN）
- 不做任何 DDL，純資料 seed
- **無條件建立**，不受 `SEED_DEMO_ACCOUNTS` 控制：正式環境也要有，測試 DB 也會有
- 不寫 `DM_USER_ROLE_LOG`、`DP_AUDIT_LOG`（比照示範帳號 seed `7b24b5dea3ad`）

## 為什麼把雜湊寫進 migration、又首次登入強制改密碼

`app/core/config.py` 註記「不再以 migration 寫入雜湊」，那條針對的是示範帳號的密碼輪替。
本帳號是例外：它須在 GCP 與院內部署後即可登入，而兩邊都是由 migration 從頭建置。

代價是**雜湊公開**——EDMS 是 public repo，任何人都能下載雜湊回去離線猜密碼，系統的
登入失敗鎖定管不到。因此：

- 初始密碼為程式產生的 12 碼亂數（符合管理者密碼門檻），明文不進 repo、issue、PR
- `MUST_CHANGE_PWD = true`：登入後前端導向強制變更密碼頁。改完後這裡的雜湊就作廢（密碼歷程有
  SEQ_NO=1 這一筆，也不能改回初始密碼）

⚠️ **暴露期是「部署完成 → 真的改了密碼」，不是「→ 首次登入」**：後端目前只有一支端點檢查
「須變更密碼」（`require_password_current`），其餘 API 不擋——直接呼叫 API 就能不改密碼一直用。
本帳號又不受閒置停用，某環境若始終沒人登入改密碼，公開的雜湊就一直有效。故**每個環境部署後
須立即以初始密碼登入並變更**；後端補閘見 #929。

## 重跑行為

| 情況 | 結果 |
|---|---|
| `USER_ID = 'edmsops'` 已存在 | 整筆跳過（含角色、密碼歷程），不覆寫既有密碼與資料；若該帳號已停用或軟刪除，記 warning（帳號實際不可用） |
| EMAIL 已被其他帳號使用 | **migration 失敗**——靜默跳過會讓維運帳號不存在而無人察覺 |

## downgrade

刪除本帳號及其角色、密碼歷程、重設 token（比照 `7b24b5dea3ad`）。僅刪 `CREATED_USER = 'SYSTEM'`
者——同 USER_ID 但非本 migration 所建的帳號不動。⚠️ 帳號使用過後再 downgrade，其建立的業務資料、
稽核紀錄仍會留下指向已刪帳號的 USER_ID（稽核表無 FK，不會擋下刪除）。
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "36af0d3943bf"
down_revision: Union[str, None] = "4c6a9a8595a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
# 與 app/core/ops_account.OPS_USER_ID 相同；migration 不 import 應用程式常數，以免日後改動回頭改寫歷史
_OPS_USER_ID = "edmsops"
_OPS_USER_NAME = "edmsops"
_OPS_EMAIL = "tbsfnoreply@gmail.com"
# 初始密碼之 bcrypt 雜湊；明文由廠商內部保管。各環境部署後須立即登入變更，見檔頭
_OPS_PWD_HASH = "$2b$12$g.VPDWHE1zAleGVtB0v5yOAQjaWQNl2YFhVXgPg0UpqZe6.LJlfvi"  # noqa: S105 — 雜湊，非明文
# 不含 DM_VIEWER：閱覽者不開放任何功能，只決定 KPI「應看」母體與發布通知收件人，給了會讓院方
# 每份全體文件的未看人數永遠多 1（SA 裁示 2026-11-05）。與 app/dm/roles/authz.OPS_DM_ROLES 相同
_DM_ROLES = ("DM_ADMIN", "DM_EDITOR", "DM_REVIEWER")
_ET_ROLE = "ADMIN"

_SELECT_BY_ID = text('SELECT "STATUS", "DELETED" FROM "DP_USER" WHERE "USER_ID" = :uid')
_SELECT_BY_EMAIL = text('SELECT 1 FROM "DP_USER" WHERE "EMAIL" = :email')

_INSERT_USER = text(
    'INSERT INTO "DP_USER" ('
    '"USER_ID", "EMAIL", "PWD_HASH", "USER_NAME", "STATUS", "LOGIN_FAIL_COUNT", '
    '"PWD_CHANGED_DATE", "MUST_CHANGE_PWD", "CREATED_USER", "CREATED_DATE", "DELETED"'
    ") VALUES (:uid, :email, :hash, :name, 'ACTIVE', 0, :now, true, :u, :now, 0)"
)

_INSERT_PWD_HIST = text(
    'INSERT INTO "DP_PWD_HIST" ("USER_ID", "SEQ_NO", "PWD_HASH", "CREATED_USER", "CREATED_DATE") '
    "VALUES (:uid, 1, :hash, :u, :now)"
)

# 角色以 upsert 復原而非單純 INSERT：DM 的角色表無 FK 至 DP_USER，可能已有指向 `edmsops`
# 的孤兒列（含已軟刪者），單純 INSERT 會撞唯一約束
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
    conn = op.get_bind()
    existing = conn.execute(_SELECT_BY_ID, {"uid": _OPS_USER_ID}).first()
    if existing is not None:
        # 已存在：不覆寫密碼與資料（重跑、或已在目標環境改過密碼）。帳號若已停用 / 軟刪除，
        # 維運帳號實際不可用——留 warning 讓部署者看得到，而非靜默成功
        status, deleted = existing
        if status != "ACTIVE" or deleted != 0:
            logger.warning(
                "廠商維運帳號已存在但不可用（STATUS=%s, DELETED=%s），本 migration 未變動，請人工確認（#927）",
                status,
                deleted,
            )
        return
    if conn.execute(_SELECT_BY_EMAIL, {"email": _OPS_EMAIL}).scalar() is not None:
        raise RuntimeError(
            f"無法建立廠商維運帳號：EMAIL {_OPS_EMAIL} 已被其他帳號使用。"
            "請先處理該帳號（改 EMAIL 或確認是否即維運帳號）後再升級（#927）。"
        )

    now = datetime.now(timezone.utc)
    params = {"uid": _OPS_USER_ID, "hash": _OPS_PWD_HASH, "now": now, "u": _SEED_USER}
    conn.execute(_INSERT_USER, {**params, "email": _OPS_EMAIL, "name": _OPS_USER_NAME})
    conn.execute(_INSERT_PWD_HIST, params)
    for role in _DM_ROLES:
        conn.execute(_UPSERT_DM_ROLE, {**params, "role": role})
    conn.execute(_UPSERT_ET_ROLE, {**params, "role": _ET_ROLE})


def downgrade() -> None:
    """移除本 migration 所建之維運帳號與其角色、密碼歷程、重設 token。

    刪除順序須先清 FK 指向 `DP_USER` 的兩張表（`DP_PWD_RESET` / `DP_PWD_HIST`）。
    """
    conn = op.get_bind()
    owned = conn.execute(
        text('SELECT 1 FROM "DP_USER" WHERE "USER_ID" = :uid AND "CREATED_USER" = :u'),
        {"uid": _OPS_USER_ID, "u": _SEED_USER},
    ).scalar()
    if owned is None:
        return

    for stmt in (
        'DELETE FROM "DM_USER_ROLE" WHERE "USER_ID" = :uid',
        'DELETE FROM "ET_USER_ROLE" WHERE "USER_ID" = :uid',
        'DELETE FROM "DP_PWD_RESET" WHERE "USER_ID" = :uid',
        'DELETE FROM "DP_PWD_HIST" WHERE "USER_ID" = :uid',
        'DELETE FROM "DP_USER" WHERE "USER_ID" = :uid',
    ):
        conn.execute(text(stmt), {"uid": _OPS_USER_ID})
