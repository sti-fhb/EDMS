"""dp_demo_accounts_rotate_password

Revision ID: 18489e30023b
Revises: 084cef76719a
Create Date: 2026-10-21 13:40:00.000000

換掉五組示範帳號的密碼，並讓**明文不再出現在原始碼**。

`7b24b5dea3ad` 以明文常數（`_DEMO_PASSWORD = "..."`）呼叫 `hash_password()` 產生雜湊。
本 repo 是 public，那串明文因此是公開的——任何人都能登入已部署的環境，其中
`admin@edms.local` 同時具 DM 與 ET 管理者角色。

本 migration 改採**只存雜湊**的作法（與主系統 TBMS 的 `tbms_base_seed` 一致）：
`PWD_HASH` 直接寫死 bcrypt 雜湊，明文另行告知、不進 repo。`$2b$12$` 為 12 輪成本，
由雜湊反推明文不可行。

異動說明：
- 影響 Table：`DP_USER`（5 列之 `PWD_HASH`、`PWD_CHANGED_DATE`），不改 schema
- 五組雜湊各有獨立 salt，故彼此不同——從 repo 看不出它們共用同一組密碼

## 為什麼不改舊 migration

`7b24b5dea3ad` 已合併（`sti-alembic-rules`：禁止修改已 merge 的 migration）。
且即便改掉，明文仍留在 git 歷史裡——public repo 的歷史無法當作已刪除。
**輪替密碼才是有效的處置，修改原始碼不是。**

## 既有環境與新環境

- 既有環境（GCP）：本 migration 一跑，舊明文立即失效
- 新環境（正式機）：`7b24b5dea3ad` 先建帳號、本支隨後覆寫雜湊，結果一致

`PWD_CHANGED_DATE` 一併更新為執行時間——密碼效期（`PWD_POLICY.EXPIRY_DAYS`）自本次
輪替起算；不更新的話，帳號可能一上線就被判定逾期而強制變更。

> ⚠️ **不寫 `DP_PWD_HIST`**：那張表記的是「使用者自己改過哪些密碼」，供防重用檢核。
> 本次是維運端輪替、非使用者行為，寫進去會讓使用者日後無法選用自己沒用過的密碼。

條件帶 `CREATED_USER = 'SYSTEM'`：只動本專案 seed 建立的那五列，不覆蓋同 `USER_ID`
的其他帳號（理論上不存在，但覆寫密碼是不可逆的，條件帶上成本為零）。
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "18489e30023b"
down_revision: Union[str, None] = "084cef76719a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

#: (USER_ID, PWD_HASH)——同一組明文、五個獨立 salt。明文不進 repo。
_HASHES: tuple[tuple[str, str], ...] = (
    ("DEMOADMIN", "$2b$12$fHO3qY.YIF9uLeC8XZFjHO8SdiWV2BjvS78Ke3sLtjAgKRXRuiYr."),
    ("DEMOEDITOR", "$2b$12$0KUQklhGFLGONHpbYTcxLOYti.U2bQYJN9Xpjw83Ye8Va21Dq2Hvu"),
    ("DEMOREVIEWER", "$2b$12$ZS0yr3F3IU4zxm7DBf5VIe4emhCDlCnBhI5bfJMxGZJ0Zprvg5uYm"),
    ("DEMOTEACHER", "$2b$12$kxTcvwDlnmcmd6fE3JOTBeKieIkAhUZD1aS/Pv6tOz7yIzSdK0bIq"),
    ("DEMOSTUDENT", "$2b$12$gksvK8ZCNDRxYOkQdC.DAe2NqzorRP5vxbYuyEgH1x6N6cm5TDwDm"),
)

_ROTATE = text(
    'UPDATE "DP_USER" SET "PWD_HASH" = :hash, "PWD_CHANGED_DATE" = :now, '
    '"UPDATED_USER" = :u, "UPDATED_DATE" = :now '
    'WHERE "USER_ID" = :uid AND "CREATED_USER" = :u'
)


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    for user_id, pwd_hash in _HASHES:
        conn.execute(_ROTATE.bindparams(hash=pwd_hash, now=now, uid=user_id, u=_SEED_USER))


def downgrade() -> None:
    """不還原舊密碼。

    舊明文是公開的，把它放回去等於把已關上的門重新打開。降版後這些帳號維持新密碼即可
    ——它們是示範帳號，密碼是什麼不影響任何 schema 或業務資料。
    """
