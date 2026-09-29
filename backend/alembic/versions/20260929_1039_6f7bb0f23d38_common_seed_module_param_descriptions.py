"""common_seed_module_param_descriptions

Revision ID: 6f7bb0f23d38
Revises: a7c31f5e9d24
Create Date: 2026-09-29 10:39:00.000000

回填 ET_ / DM_ 模組級參數之 `DP_PARAM_D.DESCRIPTION`（系統參數維護頁「說明」欄）。

`abe854a7da34` 只補了平台級（JWT / PWD_POLICY / LOGIN / MAIL）；模組級參數雖有主檔
`DP_PARAM_M.DESCRIPTION`，明細列的說明一直是 NULL——維護頁展開後看不到這個值代表什麼、
調了會有什麼後果。

異動說明：
- 影響 Table：`DP_PARAM_D`（僅更新既有列之 `DESCRIPTION`，不新增 / 刪除列、不改 schema）
- 範圍：`DM_FILE_MAX_MB` / `DM_FILE_TYPES` / `DM_REMIND_THRESHOLD` 與 `ET_` 五項，共 8 列
- 只寫入 `DESCRIPTION IS NULL` 者，**不覆蓋管理者於後台自行填寫的內容**（維護頁的說明欄
  可編輯，見 `frontend/src/dp/params/ParamEditPanel.tsx`）

三則說明刻意寫入「調錯會怎樣」，因為這些參數**沒有值域檢核**——`param_rules.py` 的
registry 只涵蓋平台級，模組級填什麼都存得進去：

- `ET_INVITATION_CODE_LENGTH`：`ET_COURSE.INVITATION_CODE` 是 `VARCHAR(8)` 硬編，填 9 以上
  要到課程發布當下才會拋錯（見 `app/et/common/invitation_code.py`）
- `ET_VIDEO_PLAYBACK_MAX_RATE`：倍速選項是前端寫死的五段，本參數只做往下過濾，設 3
  不會多出 3x 選項（見 `app/et/learning/rules.py` 之 `playback_rates`）
- `DM_FILE_TYPES`：清空不等於全部放行，會退回 fail-closed 的預設白名單
  （見 `app/dm/document/file_store.py`）
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "6f7bb0f23d38"
down_revision: Union[str, None] = "a7c31f5e9d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 模組級 VALUE 參數之中文說明（key = (PARAM_ID, PARAM_KEY)）。
# 長度對齊既有平台級說明（30～50 字）——維護頁之說明為單行 TextField，過長於列表會被截斷。
_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("DM_FILE_MAX_MB", "VALUE"): "文件版本檔與廢止附件的單檔大小上限（MB）；超過即擋下，已上傳者不受影響。",
    ("DM_FILE_TYPES", "VALUE"): (
        "允許上傳的副檔名，以半形逗號分隔；清單外一律擋下。留空會退回系統預設白名單，不會變成全部放行。"
    ),
    ("DM_REMIND_THRESHOLD", "VALUE"): (
        "送審停留於待簽核達此天數後，每日排程對審核者寄催辦信，個人專區的案件亦改標示為「催辦中」。"
    ),
    ("ET_INVITATION_CODE_LENGTH", "VALUE"): (
        "課程發布時產生的邀請碼位數（純數字）。上限 8，填更大的值會使課程發布失敗。"
    ),
    ("ET_URGENT_REMIND_DAYS", "VALUE"): (
        "閱課訖止前幾天對未完課學員寄加急提醒；每門課只寄一次，再開課後重新計算，填 0 等於停用。"
    ),
    ("ET_VIDEO_ALLOWED_FORMATS", "VALUE"): "教材影片允許上傳的容器格式，以半形逗號分隔；清單外的格式一律擋下。",
    ("ET_VIDEO_MAX_SIZE_MB", "VALUE"): "單支教材影片的檔案大小上限（MB）；超過即擋下，已上傳者不受影響。",
    ("ET_VIDEO_PLAYBACK_MAX_RATE", "VALUE"): (
        "學員可選的最高播放倍速。播放器固定 0.75 / 1 / 1.25 / 1.5 / 2 五段，本參數只能往下限縮。"
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    # SQL 本體靜態、值一律具名綁定（sti-alembic-rules）
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "DESCRIPTION" = :desc '
        'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key AND "DESCRIPTION" IS NULL'
    )
    for (param_id, param_key), desc in _DESCRIPTIONS.items():
        conn.execute(stmt.bindparams(desc=desc, param_id=param_id, param_key=param_key))


def downgrade() -> None:
    """將本 migration 寫入的說明還原為 NULL。

    以 `DESCRIPTION = :desc` 比對而非無條件清空——管理者於後台改寫過的說明不是本
    migration 種的，降版不該把它一併抹掉。
    """
    conn = op.get_bind()
    stmt = text(
        'UPDATE "DP_PARAM_D" SET "DESCRIPTION" = NULL '
        'WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key AND "DESCRIPTION" = :desc'
    )
    for (param_id, param_key), desc in _DESCRIPTIONS.items():
        conn.execute(stmt.bindparams(desc=desc, param_id=param_id, param_key=param_key))
