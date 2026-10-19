"""dm_manual_unique_include_pending_obsolete

Revision ID: 084cef76719a
Revises: d5a7e3c91f48
Create Date: 2026-10-19 17:23:31.031495

手冊唯一索引納入廢止待簽核狀態。

異動說明：
- 影響 Table：DM_DOCUMENT
- 重建部分唯一索引 `UX_DM_DOCUMENT_MANUAL_FUNC`，predicate 由
  `CATEGORY_CODE='MANUAL' AND STATUS='PUBLISHED'` 改為
  `CATEGORY_CODE='MANUAL' AND STATUS IN ('PUBLISHED','PENDING_OBSOLETE')`（#738）
- 理由：廢止待簽核之手冊**仍在架**（仍列於 DM01，見 `dm/library/repository.py`）。
  未納入時，舊手冊廢止核准前新手冊即可發布，DM01 以同一作業項目查詢會列出兩筆
- ⚠️ **本次為收緊約束**：既有資料若有「同一 FUNC_CODE 同時存在一份 PUBLISHED 與一份
  PENDING_OBSOLETE 手冊」，upgrade 會以 PostgreSQL 的
  `could not create unique index ... Key ("FUNC_CODE")=(X) is duplicated` 失敗。
  此為刻意行為——該組合要留哪一份是業務決定，不得由 migration 自行取捨。
  套用前請先跑 PR 所附的盤點查詢（同 predicate 的 GROUP BY ... HAVING COUNT(*) > 1）
- DM_DOCUMENT 為文件主檔，資料量遠小於 10 萬，不需 `CONCURRENTLY`
- downgrade 為放寬 predicate（新集合之子集），不可能撞唯一性，故安全
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "084cef76719a"
down_revision: Union[str, None] = "d5a7e3c91f48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "UX_DM_DOCUMENT_MANUAL_FUNC"
_TABLE = "DM_DOCUMENT"
_LIVE = "\"CATEGORY_CODE\" = 'MANUAL' AND \"STATUS\" IN ('PUBLISHED', 'PENDING_OBSOLETE')"
_PUBLISHED_ONLY = "\"CATEGORY_CODE\" = 'MANUAL' AND \"STATUS\" = 'PUBLISHED'"


def upgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["FUNC_CODE"], unique=True, postgresql_where=sa.text(_LIVE))


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["FUNC_CODE"], unique=True, postgresql_where=sa.text(_PUBLISHED_ONLY))
