"""common_file_path_to_relative

Revision ID: 676114dc0672
Revises: 1a85b7fe2cff
Create Date: 2026-08-28 15:46:39.497948

把既有之絕對 `FILE_PATH` 正規化為「相對於 storage root 的片段」（#233）。

## 為何不以當前 storage root 為前綴 strip

直覺寫法是「去掉 `settings.DM_FILE_STORAGE_ROOT` 前綴」，但那會讓 migration 的結果
**取決於執行時載入哪一份 `.env`**——各 worktree 的 `backend/.env` 是從主 repo 原封複製的
（見 #239），主 repo 未設 storage root 時預設值又是相對路徑、依 process 工作目錄解析，
於是同一個資料庫從不同目錄跑 `alembic upgrade head` 會得到不同的 root。前綴對不上時
strip 靜默失敗、不報錯，要等下載壞掉才會發現。

改以**路徑自身的結構**為依據即可消除這個變數：落盤結構恆為
`{root}/{doc_id}/{file_id}.{ext}`（DM）與 `{root}/{material_id}/{uuid}.{ext}`（ET），
故正規化分隔符後**取最後兩段**即為相對片段。不讀 settings、不碰檔案系統。

## 為何不是「搜尋識別碼首次出現處」

初版用 `position(key in path)` 取切點，Code Review 實測抓出這會切錯：`position` 只找
**第一個**出現位置、未錨定分隔符邊界，短識別碼極易提前誤命中。

| 識別碼 | 原始路徑 | position 寫法 | 取最後兩段 |
|--------|---------|--------------|-----------|
| `2` | `\data\srv2\et_videos\2\29ef.mp4` | `2/et_videos/2/29ef.mp4` ❌ | `2/29ef.mp4` ✓ |
| `1` | `\srv1\v1\et_videos\1\abc.mp4` | `1/v1/et_videos/1/abc.mp4` ❌ | `1/abc.mp4` ✓ |
| `DM-X` | `/srv/DM-X/DM-X/f.pdf` | `DM-X/DM-X/f.pdf` ❌ | `DM-X/f.pdf` ✓ |

最惡劣之處是**錯得無聲**：`position() > 0` 確實成立，所以「切不出來」的盤點條件抓不到，
錯誤值會被寫入且 log 顯示轉換成功；加上 `downgrade` 是 no-op，只能事後人工修 DB。

現行寫法另加守門：切出的第一段必須**恰好等於**該列識別碼，同時擋掉「切不出來」與
「切出來但切錯」——後者正是 position 寫法無從察覺的那一類。

## 未通過守門的列

原樣保留，並於 log 印出筆數。該類列必然已是壞資料（現況即被 `resolve_within_root`
擋下回 404），不因本 migration 而變差；設為 NULL 反而會抹掉「這一版曾經有檔」的事實，
且 `DM_DOC_VERSION` 的草稿本就允許無檔（data-model L266-269），NULL 會讓壞掉的已發布版
看起來像正常的無檔草稿。

## downgrade

**刻意留空**（`sti-alembic-rules.md:100-104`「若 downgrade 不安全或無意義，留空並加註
原因」）：相對 → 絕對需要「當時的 root」，而 downgrade 執行時的 root 未必相同，還原出
的路徑可能是錯的。改存相對路徑後的資料在新版程式碼下本就可用，無須還原。
"""

import logging
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "676114dc0672"
down_revision: Union[str, None] = "1a85b7fe2cff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# 取「最後兩段」而非搜尋識別碼首次出現處。
#
# ⚠️ 為何不用 `position(key in path)`：那只找**第一個**出現位置、未錨定在分隔符邊界，
# 短識別碼極易提前誤命中。實測（MATERIAL_ID=2、路徑 `\data\srv2\et_videos\2\29ef.mp4`）
# 會切出 `2/et_videos/2/29ef.mp4`——**錯誤但看似成功**，且因為 `position() > 0` 確實成立，
# 「切不出來」的盤點條件（`= 0`）完全抓不到，會被靜默寫入錯誤值。DM 亦然：DOC_ID 在路徑中
# 出現兩次時（`/srv/DM-X/DM-X/f.pdf`）會切成 `DM-X/DM-X/f.pdf`。
#
# 落盤結構恆為 `{root}/{識別碼}/{檔名}`，故直接取最後兩段最穩：先把 `\` 正規化為 `/`
# （Windows 落盤產出的 `\` 搬到 POSIX 讀不到——`\` 在 POSIX 是合法檔名字元、不作分隔符），
# 再以貪婪 `^.*/` 吃掉前綴。已是相對片段者（僅一個 `/`）不匹配，regexp_replace 原樣回傳，
# 故本轉換為冪等。
_EXTRACT = r"regexp_replace(replace({col}, '\', '/'), '^.*/([^/]+/[^/]+)$', '\1')"

# 守門：切出的第一段必須**恰好等於**該列自身的識別碼。這同時擋掉「切不出來」與
# 「切出來但切錯」兩種情形——後者正是 position 寫法無法察覺的那一類。
_GUARD = "split_part({extract}, '/', 1) = {key}"


def _update(table: str, col: str, key: str, *, not_null: bool = True) -> str:
    extract = _EXTRACT.format(col=col)
    where = [f"{_GUARD.format(extract=extract, key=key)}"]
    if not_null:
        where.insert(0, f"{col} IS NOT NULL")
    return f'UPDATE "{table}" SET {col} = {extract} WHERE ' + " AND ".join(where)


def _leftover(table: str, col: str, key: str, label: str, *, not_null: bool = True) -> str:
    extract = _EXTRACT.format(col=col)
    where = [f"NOT ({_GUARD.format(extract=extract, key=key)})"]
    if not_null:
        where.insert(0, f"{col} IS NOT NULL")
    return f"SELECT '{label}' AS col, count(*) AS n FROM \"{table}\" WHERE " + " AND ".join(where)


#: (欄位標籤, UPDATE 陳述式)——測試以此常數執行，避免測試與 migration 之 SQL drift
TARGETS: tuple[tuple[str, str], ...] = (
    ("DM_DOC_VERSION.FILE_PATH", _update("DM_DOC_VERSION", '"FILE_PATH"', '"DOC_ID"')),
    # OBSOLETE_FILE_PATH 亦落在 {root}/{doc_id}/ 下（沿用 save_upload），切點同為 DOC_ID
    ("DM_REVIEW.OBSOLETE_FILE_PATH", _update("DM_REVIEW", '"OBSOLETE_FILE_PATH"', '"DOC_ID"')),
    # 影片落在 {root}/{material_id}/ 下（promote 之 video_id_hint 即 MATERIAL_ID）
    (
        "ET_MATERIAL_VIDEO.FILE_PATH",
        _update("ET_MATERIAL_VIDEO", '"FILE_PATH"', '"MATERIAL_ID"::text', not_null=False),
    ),
)

#: 三個欄位中未通過守門者之盤點查詢（切不出來、或切出的第一段對不上識別碼），供 log 提示
LEFTOVER_SQL = " UNION ALL ".join(
    (
        _leftover("DM_DOC_VERSION", '"FILE_PATH"', '"DOC_ID"', "DM_DOC_VERSION.FILE_PATH"),
        _leftover("DM_REVIEW", '"OBSOLETE_FILE_PATH"', '"DOC_ID"', "DM_REVIEW.OBSOLETE_FILE_PATH"),
        _leftover(
            "ET_MATERIAL_VIDEO", '"FILE_PATH"', '"MATERIAL_ID"::text', "ET_MATERIAL_VIDEO.FILE_PATH", not_null=False
        ),
    )
)


def upgrade() -> None:
    conn = op.get_bind()
    for label, sql in TARGETS:
        result = conn.execute(text(sql))
        logger.info("FILE_PATH → 相對路徑：%s 轉換 %s 列", label, result.rowcount)

    for row in conn.execute(text(LEFTOVER_SQL)):
        if row.n:
            # 路徑不含自身識別碼 → 無從切出相對片段。原樣保留（該類列現況即已 404）。
            logger.warning(
                "FILE_PATH 仍為絕對路徑且無法轉換：%s 共 %s 列（實體檔案多半已失聯，維持原值）",
                row.col,
                row.n,
            )


def downgrade() -> None:
    # 含資料操作且不可逆，downgrade 不實作（見模組 docstring「downgrade」段）：
    # 相對 → 絕對需要「當時的 root」，downgrade 當下的 root 未必相同，假還原會產生錯誤路徑。
    pass
