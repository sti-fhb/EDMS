"""merge_et_materials_quizzes_and_dm_us9

Revision ID: 8ce307803975
Revises: 4e911375d095, 6eea417bdf8a
Create Date: 2026-08-27 13:53:17.171582

合併兩條自 `e6a4c7b18d93`（#202 之 `ET_CHAPTER` 部分唯一索引）分出的鏈：

| head | 來源 | 內容 |
|------|------|------|
| `4e911375d095` | 本分支（#203）| `ET_QUIZ.DESCRIPTION`、`ET_ITEM` / `ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC` 之部分唯一索引 |
| `6eea417bdf8a` | main（#219 DM US9）| 其自身亦為 merge——合併 DM US9 個人專區與 ET 章節順序兩條鏈 |

**無實際 schema 變更**——兩條鏈改的是不同的表（ET 教材 / 測驗 vs DM 文件與範本），
沒有交集需要調解，故 `upgrade` / `downgrade` 皆為空。此檔的唯一作用是讓 revision
圖回到單一 head，否則 `alembic upgrade head` 會因「Multiple head revisions」而
失敗——2026-08-27 之 CI 即因此紅燈。
"""

from typing import Sequence, Union

revision: str = "8ce307803975"
down_revision: Union[str, None] = ("4e911375d095", "6eea417bdf8a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """無變更——僅收斂 revision 圖。"""


def downgrade() -> None:
    """無變更——降級時 alembic 自行拆回兩條鏈。"""
