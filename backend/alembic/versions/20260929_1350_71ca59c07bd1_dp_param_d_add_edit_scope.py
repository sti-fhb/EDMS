"""dp_param_d_add_edit_scope

Revision ID: 71ca59c07bd1
Revises: 6f7bb0f23d38
Create Date: 2026-09-29 13:50:00.000000

DP_PARAM_D 新增維護層級欄位 EDIT_SCOPE（#171）。

異動說明：
- 影響 Table：`DP_PARAM_D`
- `EDIT_SCOPE`：VARCHAR(20)、NOT NULL，值為 `ADMIN` / `READONLY` / `HIDDEN`（分三步加）
- `CK_DP_PARAM_D_EDIT_SCOPE`：限制上述三值
- 回填既有 30 列：25 個 VALUE 明細依分類表逐列指定，`ACTION_TYPE`（LIST）整組填 `HIDDEN`

為何**不設 `server_default`**（本 migration 的護欄，勿於日後「順手補上」）：
  `ADD COLUMN ... DEFAULT` 會立刻把所有既有列填滿，Step 3 的 `SET NOT NULL` 便永遠成立——
  分類表漏列一筆就**靜默**變成 `ADMIN`（可編輯），正是本 issue 要防的形狀。維持無預設值時，
  漏填的列在 Step 3 直接讓 migration 失敗，錯誤看得見。
  新列的預設由 model 的 Python-side `default="ADMIN"` 負責（比照既有 `IS_ENABLED`）。
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "71ca59c07bd1"
down_revision: Union[str, None] = "6f7bb0f23d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 25 個 VALUE 明細之維護層級（key = (PARAM_ID, PARAM_KEY)）。分類與理由見 #171 issue body。
#
# 判準摘要：
# - ADMIN    ：純業務／資安政策，值域寬鬆、改錯可回復，本來就該由甲方決定
# - READONLY ：管理者需知現值以回答使用者，但值受實作或環境限制，改錯會造成功能異常
# - HIDDEN   ：純技術／部署調校，業務端不需知道，出現在畫面只是雜訊
_EDIT_SCOPES: dict[tuple[str, str], str] = {
    # ── 平台級：密碼政策（6）──
    ("PWD_POLICY", "MIN_LEN"): "ADMIN",
    ("PWD_POLICY", "ADMIN_MIN_LEN"): "ADMIN",
    ("PWD_POLICY", "CHAR_TYPES"): "ADMIN",
    ("PWD_POLICY", "HISTORY_COUNT"): "ADMIN",
    ("PWD_POLICY", "EXPIRY_DAYS"): "ADMIN",
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS"): "ADMIN",
    # ── 平台級：登入（6）──
    ("LOGIN", "FAIL_LOCK_COUNT"): "ADMIN",
    ("LOGIN", "LOCK_MINUTES"): "ADMIN",
    ("LOGIN", "IDLE_DISABLE_DAYS"): "ADMIN",
    ("LOGIN", "RESET_TOKEN_TTL_MIN"): "ADMIN",
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN"): "ADMIN",
    # 防濫發調校：調小則防線失效、調大則使用者卡住；但管理者需能回答「為何要等 10 分鐘才能重寄」
    ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC"): "READONLY",
    # ── 平台級：JWT（2）──
    # spec 硬性規定不得超過 15 分鐘（EDMS 認定為含敏感資料系統）；開放改＝開放違反資安要求
    ("JWT", "ACCESS_TTL_MIN"): "READONLY",
    ("JWT", "RENEW_MAX_HOURS"): "READONLY",
    # ── 平台級：寄信引擎（3）──
    # 陷阱：worker 輪詢間隔 60 秒寫死於 notify/worker.py，調高本值不會等比例變快
    ("MAIL", "RATE_PER_MIN"): "HIDDEN",
    ("MAIL", "RETRY_MAX"): "HIDDEN",
    ("MAIL", "RETRY_INTERVAL_MIN"): "HIDDEN",
    # ── DM 模組級（3）──
    ("DM_REMIND_THRESHOLD", "VALUE"): "ADMIN",
    # spec 明訂「由 IT 設定」；且與預覽邏輯耦合（PDF / 圖片可預覽、Office 僅下載）
    ("DM_FILE_MAX_MB", "VALUE"): "READONLY",
    ("DM_FILE_TYPES", "VALUE"): "READONLY",
    # ── ET 模組級（5）──
    ("ET_URGENT_REMIND_DAYS", "VALUE"): "ADMIN",
    # #170 之案例：受瀏覽器 HTML5 <video> 支援限制，填 .mov 會靜默故障（傳得上去、播不出來）
    ("ET_VIDEO_ALLOWED_FORMATS", "VALUE"): "READONLY",
    ("ET_VIDEO_MAX_SIZE_MB", "VALUE"): "READONLY",
    # 倍速選項為前端寫死的五段，本參數只做往下過濾——設 3 不會多出 3x 選項
    ("ET_VIDEO_PLAYBACK_MAX_RATE", "VALUE"): "READONLY",
    # ET_COURSE.INVITATION_CODE 為 VARCHAR(8) 硬編，填 9 以上要到課程發布當下才拋錯
    ("ET_INVITATION_CODE_LENGTH", "VALUE"): "READONLY",
}

# 系統寫死的 enum 清單：程式碼直接寫碼值（各 service 傳入 action_type、
# audit/query_service.py 之 _ACTION_LABELS 對照），改名或停用會使稽核寫入與查詢下拉對不上。
# 以 PARAM_ID 整組回填而非逐 PARAM_KEY 列舉——清單項數日後若增減，此處仍涵蓋得到。
_HIDDEN_MASTERS: tuple[str, ...] = ("ACTION_TYPE",)

_VALID_SCOPES = ("ADMIN", "READONLY", "HIDDEN")


def upgrade() -> None:
    # Step 1：先加 nullable 欄位（既有資料才能通過）。刻意不給 server_default，見 docstring。
    op.add_column("DP_PARAM_D", sa.Column("EDIT_SCOPE", sa.String(20), nullable=True))

    conn = op.get_bind()
    # Step 2a：逐列回填 VALUE 明細（SQL 本體靜態、值具名綁定，sti-alembic-rules）
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "EDIT_SCOPE" = :scope '
        'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key'
    )
    for (param_id, param_key), scope in _EDIT_SCOPES.items():
        conn.execute(stmt.bindparams(scope=scope, param_id=param_id, param_key=param_key))

    # Step 2b：系統 enum 清單整組填 HIDDEN
    master_stmt = text('UPDATE "DP_PARAM_D" SET "EDIT_SCOPE" = :scope WHERE "PARAM_ID" = :param_id')
    for param_id in _HIDDEN_MASTERS:
        conn.execute(master_stmt.bindparams(scope="HIDDEN", param_id=param_id))

    # Step 3：設 NOT NULL。這同時就是「分類表無漏列」的護欄——漏填的列會讓本步驟失敗
    # （sti-alembic-rules 明令不寫 migration 一次性驗收測試，此處以 DB 約束取代斷言）。
    op.alter_column("DP_PARAM_D", "EDIT_SCOPE", existing_type=sa.String(20), nullable=False)

    # Step 4：限定三值。決策 2 指定 READONLY / HIDDEN 之變更途徑為「IT 直接操作 DB」，
    # 沒有這道約束，IT 打成 'readonly' 會讓該列被服務層視為未知值——服務層雖已寫成
    # 「只有 ADMIN 可改」而 fail-closed，但錯誤直到有人回報「改不動」才會被發現。
    op.create_check_constraint(
        "CK_DP_PARAM_D_EDIT_SCOPE",
        "DP_PARAM_D",
        sa.column("EDIT_SCOPE").in_(_VALID_SCOPES),
    )


def downgrade() -> None:
    op.drop_constraint("CK_DP_PARAM_D_EDIT_SCOPE", "DP_PARAM_D", type_="check")
    op.drop_column("DP_PARAM_D", "EDIT_SCOPE")
