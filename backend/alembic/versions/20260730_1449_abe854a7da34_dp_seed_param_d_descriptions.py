"""dp_seed_param_d_descriptions

Revision ID: abe854a7da34
Revises: 9b309342e9f3
Create Date: 2026-07-30 14:49:47.671120

回填 DP_PARAM_D.DESCRIPTION（平台級 VALUE 參數之中文說明，供系統參數維護頁「說明」欄顯示，#99）。

異動說明：
- 影響 Table：DP_PARAM_D（僅更新既有列之 DESCRIPTION，不新增 / 刪除列、不改 schema）
- 範圍：JWT / PWD_POLICY / LOGIN / MAIL 之平台級 VALUE 明細
- downgrade：將這些列之 DESCRIPTION 還原為 NULL
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "abe854a7da34"
down_revision: Union[str, None] = "9b309342e9f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 平台級 VALUE 參數之中文說明（key = (PARAM_ID, PARAM_KEY)）。對齊 spec_us5 §參數型別 / 值域驗證規則。
_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("JWT", "ACCESS_TTL_MIN"): "登入後閒置未操作達此分鐘數即自動登出、token 失效。",
    ("JWT", "RENEW_MAX_HOURS"): "自本次登入起，token 可靜默換發的最長時數；逾時需重新登入。",
    ("PWD_POLICY", "MIN_LEN"): "一般使用者密碼的最小字元長度。",
    ("PWD_POLICY", "ADMIN_MIN_LEN"): "具管理權限帳號的密碼最小字元長度（通常較一般帳號嚴格）。",
    ("PWD_POLICY", "CHAR_TYPES"): "密碼須包含的字元種類數（大寫 / 小寫 / 數字 / 符號中至少幾類）。",
    ("PWD_POLICY", "HISTORY_COUNT"): "變更密碼時，不得與最近使用過的幾次密碼重複。",
    ("PWD_POLICY", "EXPIRY_DAYS"): "密碼自變更起的最長有效天數；逾期登入時強制變更。",
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS"): "密碼到期前幾天開始提醒使用者變更。",
    ("LOGIN", "FAIL_LOCK_COUNT"): "連續登入失敗達此次數即自動鎖定帳號。",
    ("LOGIN", "LOCK_MINUTES"): "帳號鎖定後，自動解鎖前的等待分鐘數。",
    ("LOGIN", "RESET_TOKEN_TTL_MIN"): "忘記密碼重設連結的有效分鐘數。",
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): "變更 Email 的驗證連結有效分鐘數。",
    ("LOGIN", "IDLE_DISABLE_DAYS"): "帳號閒置（未登入）達此天數即自動停用。",
    ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC"): "重寄驗證信 / 重設信的冷卻秒數，避免短時間內重複寄送。",
    ("MAIL", "RATE_PER_MIN"): "系統每分鐘寄出信件的封數上限；超過則排隊延後寄送。",
    ("MAIL", "RETRY_MAX"): "單封信寄送失敗時的最大重試次數。",
    ("MAIL", "RETRY_INTERVAL_MIN"): "寄信失敗後，每次重試之間的間隔分鐘數。",
}


def upgrade() -> None:
    conn = op.get_bind()
    # SQL 本體靜態、值一律具名綁定（sti-alembic-rules）
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "DESCRIPTION" = :desc WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key'
    )
    for (param_id, param_key), desc in _DESCRIPTIONS.items():
        conn.execute(stmt.bindparams(desc=desc, param_id=param_id, param_key=param_key))


def downgrade() -> None:
    conn = op.get_bind()
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "DESCRIPTION" = NULL WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key'
    )
    for param_id, param_key in _DESCRIPTIONS:
        conn.execute(stmt.bindparams(param_id=param_id, param_key=param_key))
