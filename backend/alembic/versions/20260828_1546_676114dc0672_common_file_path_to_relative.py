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

改以**列自身的識別碼**為切點即可消除這個變數：落盤路徑結構恆為
`{root}/{doc_id}/{file_id}.{ext}`（DM）與 `{root}/{material_id}/{uuid}.{ext}`（ET），
故從路徑中該識別碼第一次出現處往後取，即為相對片段。不讀 settings、不碰檔案系統。

## 切不出來的列

路徑不含自身識別碼者原樣保留，並於 log 印出筆數。該類列必然已是壞資料（現況即被
`resolve_within_root` 擋下回 404），不因本 migration 而變差；設為 NULL 反而會抹掉
「這一版曾經有檔」的事實，且 `DM_DOC_VERSION` 的草稿本就允許無檔（data-model
L266-269），NULL 會讓壞掉的已發布版看起來像正常的無檔草稿。

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

# 反斜線一律轉為 `/`：Windows 落盤產出的 `\` 搬到 POSIX 就讀不到（`\` 在 POSIX 是合法
# 檔名字元、不作分隔符）。相對片段的分隔符必須是可攜的那一個。
_TO_RELATIVE = "replace(substring({col} from position({key} in {col})), '\\', '/')"

#: (欄位標籤, UPDATE 陳述式)——測試以此常數執行，避免測試與 migration 之 SQL drift
TARGETS: tuple[tuple[str, str], ...] = (
    (
        "DM_DOC_VERSION.FILE_PATH",
        'UPDATE "DM_DOC_VERSION" SET "FILE_PATH" = '
        + _TO_RELATIVE.format(col='"FILE_PATH"', key='"DOC_ID"')
        + ' WHERE "FILE_PATH" IS NOT NULL AND position("DOC_ID" in "FILE_PATH") > 0',
    ),
    (
        # OBSOLETE_FILE_PATH 亦落在 {root}/{doc_id}/ 下（沿用 save_upload），切點同為 DOC_ID
        "DM_REVIEW.OBSOLETE_FILE_PATH",
        'UPDATE "DM_REVIEW" SET "OBSOLETE_FILE_PATH" = '
        + _TO_RELATIVE.format(col='"OBSOLETE_FILE_PATH"', key='"DOC_ID"')
        + ' WHERE "OBSOLETE_FILE_PATH" IS NOT NULL'
        + ' AND position("DOC_ID" in "OBSOLETE_FILE_PATH") > 0',
    ),
    (
        # 影片落在 {root}/{material_id}/ 下（promote 之 video_id_hint 即 MATERIAL_ID）
        "ET_MATERIAL_VIDEO.FILE_PATH",
        'UPDATE "ET_MATERIAL_VIDEO" SET "FILE_PATH" = '
        + _TO_RELATIVE.format(col='"FILE_PATH"', key='"MATERIAL_ID"::text')
        + ' WHERE position("MATERIAL_ID"::text in "FILE_PATH") > 0',
    ),
)

#: 三個欄位中切不出相對片段者之盤點查詢，供 log 提示（不修改資料）
LEFTOVER_SQL = """
SELECT 'DM_DOC_VERSION.FILE_PATH' AS col, count(*) AS n FROM "DM_DOC_VERSION"
 WHERE "FILE_PATH" IS NOT NULL AND position("DOC_ID" in "FILE_PATH") = 0
UNION ALL
SELECT 'DM_REVIEW.OBSOLETE_FILE_PATH', count(*) FROM "DM_REVIEW"
 WHERE "OBSOLETE_FILE_PATH" IS NOT NULL AND position("DOC_ID" in "OBSOLETE_FILE_PATH") = 0
UNION ALL
SELECT 'ET_MATERIAL_VIDEO.FILE_PATH', count(*) FROM "ET_MATERIAL_VIDEO"
 WHERE position("MATERIAL_ID"::text in "FILE_PATH") = 0
"""


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
