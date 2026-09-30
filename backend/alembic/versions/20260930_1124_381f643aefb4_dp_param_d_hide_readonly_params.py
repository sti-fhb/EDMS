"""dp_param_d_hide_readonly_params

Revision ID: 381f643aefb4
Revises: 71ca59c07bd1
Create Date: 2026-09-30 11:24:00.000000

9 項 READONLY 參數改為 HIDDEN，不再出現於 DP07（#459）。

異動說明：
- 影響 Table：`DP_PARAM_D`（僅更新 `EDIT_SCOPE`，不新增 / 刪除列、不改 schema）
- 範圍：`71ca59c07bd1` 判為 `READONLY` 的 9 列，全數改為 `HIDDEN`
- 分佈由 `ADMIN 13 / READONLY 9 / HIDDEN 8` 變為 `ADMIN 13 / READONLY 0 / HIDDEN 17`

裁示來由（2026-09-30）：#171 上線後實際操作，認定這些參數不該出現在維護頁。
`READONLY`（顯示現值但不可編輯）當初的理由是「管理者需知現值以回答使用者」，
該理由被推翻——代價是管理者從此無法在系統內回答「為何 15 分鐘被登出」
「單檔上限多少」，須改問 IT。已載入 spec_us5。

⚠️ **`EDIT_SCOPE` 欄位與三值列舉不移除**，`CK_DP_PARAM_D_EDIT_SCOPE` 亦不變。
`READONLY` 僅是目前無成員，保留供日後使用；其程式碼路徑仍有測試覆蓋
（測試改用自建資料，見 `test_dp_params_maintain.py`）。

⚠️ 兩個主檔因所有明細皆變 `HIDDEN` 而**整個從維護頁消失**：`JWT`（2 列）與
`MAIL`（3 列，`71ca59c07bd1` 時即已全 HIDDEN）。`LOGIN` 則成為混合主檔——
6 列中 5 列可見、`VERIFY_SEND_COOLDOWN_SEC` 隱藏。

本異動**不影響執行期讀取**：`EDIT_SCOPE` 只作用於維護面，SRVDP001
（`ParamService`）照常讀得到這 9 項的值。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "381f643aefb4"
down_revision: Union[str, None] = "71ca59c07bd1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `71ca59c07bd1` 判為 READONLY 的 9 列。逐列列舉而非 `WHERE EDIT_SCOPE='READONLY'`——
# 後者會把日後任何新標為 READONLY 的列一併掃掉，而本次裁示只針對這 9 項。
_TARGETS: tuple[tuple[str, str], ...] = (
    # 平台級
    ("JWT", "ACCESS_TTL_MIN"),
    ("JWT", "RENEW_MAX_HOURS"),
    ("LOGIN", "VERIFY_SEND_COOLDOWN_SEC"),
    # DM 模組級
    ("DM_FILE_MAX_MB", "VALUE"),
    ("DM_FILE_TYPES", "VALUE"),
    # ET 模組級
    ("ET_VIDEO_ALLOWED_FORMATS", "VALUE"),
    ("ET_VIDEO_MAX_SIZE_MB", "VALUE"),
    ("ET_VIDEO_PLAYBACK_MAX_RATE", "VALUE"),
    ("ET_INVITATION_CODE_LENGTH", "VALUE"),
)


def _apply(from_scope: str, to_scope: str) -> None:
    """把 `_TARGETS` 各列由 from_scope 改為 to_scope（SQL 靜態、值具名綁定）。

    帶 `EDIT_SCOPE = :from_scope` 條件而非無條件覆寫，擋的是**這 9 列之一已被人為改成
    別的值**的情形：決策 2 指定變更途徑為「IT 直接操作 DB」，若 IT 把某列改成 `ADMIN`，
    無條件覆寫會在升／降版時把那個決定默默蓋掉。有條件時該列原樣保留。

    ⚠️ 這個條件**不負責**界定影響範圍——範圍由 `_TARGETS` 決定。`MAIL` / `ACTION_TYPE`
    不會被碰到是因為它們不在 `_TARGETS` 裡，不是因為這個條件。
    （2026-09-30 變異檢查發現原註解把兩者混為一談：移除條件後行為不變，說明先前
    「降版不會誤翻 MAIL」的驗證並未驗到宣稱的那個機制。）

    ⚠️ 依 `sti-alembic-rules` 不為 migration 寫一次性驗收測試，故本條件**沒有自動測試**
    覆蓋——改動時請手動跑一次升／降版並比對分佈。
    """
    conn = op.get_bind()
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "EDIT_SCOPE" = :to_scope '
        'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key AND "EDIT_SCOPE" = :from_scope'
    )
    for param_id, param_key in _TARGETS:
        conn.execute(stmt.bindparams(to_scope=to_scope, from_scope=from_scope, param_id=param_id, param_key=param_key))


def upgrade() -> None:
    _apply(from_scope="READONLY", to_scope="HIDDEN")


def downgrade() -> None:
    """還原為 READONLY。

    ⚠️ 還原後這 9 項會重新出現於 DP07（顯示現值、無編輯入口）。

    範圍由 `_TARGETS` 界定，`MAIL` 三項與 `ACTION_TYPE` 五項本來就不在其中，降版不會碰到
    ——**這與 `from_scope` 條件無關**，別把兩件事混為一談（那個條件擋的是下面那種情形）。
    """
    _apply(from_scope="HIDDEN", to_scope="READONLY")
