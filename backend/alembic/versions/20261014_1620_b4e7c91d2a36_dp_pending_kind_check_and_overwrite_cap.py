"""dp_pending_kind_check_and_overwrite_cap

Revision ID: b4e7c91d2a36
Revises: a3f9c21e5d84
Create Date: 2026-10-14 16:20:00.000000

`DP_PENDING_REGISTRATION.KIND` 值域封閉（#215）＋ 註冊重建次數上限參數（#234）。

異動說明：
- 影響 Table：`DP_PENDING_REGISTRATION`（加 CHECK）、`DP_PARAM_D`（新增一列）
- `CK_DP_PENDING_REGISTRATION_KIND`：限制 `KIND IN ('SELF_REGISTER', 'ADMIN_INVITE')`
- seed `LOGIN / REGISTER_OVERWRITE_MAX_PER_DAY = 5`，`EDIT_SCOPE='HIDDEN'`
- `downgrade` 逐項可逆：drop constraint + 精確 WHERE 刪該列（不清空整表）

### #215：為什麼值域要在 DB 層封閉

`KIND` 原為 `VARCHAR(20) NOT NULL`、無 CHECK。一筆 `KIND='ADMIN-INVITE'`（連字號 typo）
的列在**所有 UI 上都看不見**——邀請清單濾 `KIND='ADMIN_INVITE'` 撈不到、`DP_USER` 也查不到，
卻佔住 `EMAIL` 唯一鍵，使管理者代建該 Email 恆回誤導的 409「此 Email 已被註冊」，
且連取消都做不到（取消邀請需 `invite_id`，而該列不在清單上）。

#137 的護欄測試證明的是「同一個值只定義一次」，**不是**「只有這兩個值進得了 DB」；
兩者互補。採 DB CHECK 而非應用層斷言的理由見 #215 的 2026-10-14 裁示：DP 已有同形先例
`CK_DP_PARAM_D_EDIT_SCOPE`，且應用層只守得住經 `AuthRepository` 的路徑，而真正的危害
來自日後繞過它的新程式碼。

⚠️ **字面量刻意不從 `app.dp.user.kinds` import**：migration 是歷史快照，依賴 app 常數會讓
「改常數」回頭改變既有 migration 的語意（`kinds.py` docstring 已載明此原則，其護欄測試
亦刻意不掃 `alembic/versions/`）。

⚠️ 加 CHECK 時 PostgreSQL 會驗既有列，有違反值即**失敗並回滾**——這是刻意的 fail-loud。
本表為暫存表（TTL 30 分鐘 + `SCHDP001` 逾期滿 1 天清理），不會累積陳年資料。

### #234：為什麼上限要做成參數、且設 HIDDEN

上限值的正確值取決於真實使用者行為（多少人會一天內重送四次），目前無資料，故做成參數
以免重新部署（2026-10-14 裁示，預設 5）。

`EDIT_SCOPE='HIDDEN'` 比照同群組的 `VERIFY_SEND_COOLDOWN_SEC`（#459 把該類防濫用旋鈕
移出維護頁）。更實際的理由：**占用時間是 `N × TTL`，而該互鎖在 DP03 畫面上看不到**——
管理者看到「每日上限 5」會覺得保守而調到 10，卻無從得知同頁的 `RESET_TOKEN_TTL_MIN`
若也調到 120，占用就從 2.5 小時變成 20 小時／日，本修法形同失效。
值域守門在**讀取端**（`app/dp/user/router.py` 的 `_overwrite_max`，夾回 [1, 10] 並留 warning log）。
⛔ **刻意不放 `param_rules.py` 的 `IntRule`**：`EDIT_SCOPE='HIDDEN'` 使 `is_editable_scope` 的 403
擋在值域檢核**之前**，那條規則永遠走不到；而真正走得到的修改路徑是 IT 直接下 SQL，
`get_int_param` 對整數不設界。理由與互鎖說明見該函式的 docstring。
（本句原寫「守門寫在 param_rules.py」——那是 docstring 先於決定寫下、決定改變後未回頭更正，
 由 2026-10-14 的 code review 抓出。）
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "b4e7c91d2a36"
down_revision: Union[str, None] = "a3f9c21e5d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND_CONSTRAINT = "CK_DP_PENDING_REGISTRATION_KIND"
# 刻意為字面量而非 import（見 docstring）
_VALID_KINDS = ("SELF_REGISTER", "ADMIN_INVITE")

_PARAM_ID = "LOGIN"
_PARAM_KEY = "REGISTER_OVERWRITE_MAX_PER_DAY"


def upgrade() -> None:
    op.create_check_constraint(
        _KIND_CONSTRAINT,
        "DP_PENDING_REGISTRATION",
        sa.column("KIND").in_(_VALID_KINDS),
    )

    # 既存則跳過：本 migration 可能在已手動補過的環境重跑（sti-alembic-rules §Seed Data）。
    # SQL 本體靜態；會變動的值一律具名綁定，`SYSTEM` / `now()` / 旗標為靜態字面量。
    op.get_bind().execute(
        text(
            'INSERT INTO "DP_PARAM_D" '
            '("PARAM_ID", "PARAM_KEY", "PARAM_NAME", "PARAM_VALUE", "DESCRIPTION", '
            '"IS_ENABLED", "EDIT_SCOPE", "CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:param_id, :param_key, :param_name, :param_value, :description, "
            "true, 'HIDDEN', 'SYSTEM', now(), 0) "
            'ON CONFLICT ("PARAM_ID", "PARAM_KEY") DO NOTHING'
        ).bindparams(
            param_id=_PARAM_ID,
            param_key=_PARAM_KEY,
            param_name="同一 Email 每日重建待驗證列上限",
            param_value="5",
            description=(
                "匿名註冊 / 重寄對同一 Email 於 24 小時內實際重建待驗證列並寄信的次數上限；"
                "超過即不再刷新效期也不寄信，使該列終會逾期（#234）。"
                "占用時間為本值 × RESET_TOKEN_TTL_MIN，兩者互鎖。"
            ),
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key').bindparams(
            param_id=_PARAM_ID,
            param_key=_PARAM_KEY,
        )
    )
    op.drop_constraint(_KIND_CONSTRAINT, "DP_PENDING_REGISTRATION", type_="check")
