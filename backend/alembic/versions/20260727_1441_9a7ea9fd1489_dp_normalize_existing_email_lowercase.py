"""dp_normalize_existing_email_lowercase

Revision ID: 9a7ea9fd1489
Revises: 440984dc7cd4
Create Date: 2026-07-27 14:41:21.919339

既有 email 轉小寫，對齊 #35 schema 層正規化（查詢 / 限流 key 一致）。

異動說明（#35 email 大小寫正規化）：
- 影響 Table：DP_USER、DP_PENDING_REGISTRATION（皆 data-only，無 schema 變更）
- 將既有 EMAIL 轉小寫，使正規化後（一律小寫）查詢仍命中舊帳號
- 轉換前先偵測「僅大小寫不同」之碰撞列（lower 後會撞 EMAIL UNIQUE）；有碰撞則中止並列出，交人工處理
- downgrade 不可逆（無法還原原始大小寫），不實作
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "9a7ea9fd1489"
down_revision: Union[str, None] = "440984dc7cd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("DP_USER", "DP_PENDING_REGISTRATION")


def upgrade() -> None:
    conn = op.get_bind()
    for tbl in _TABLES:
        # 碰撞偵測：轉小寫後是否有兩列以上共用同一 email（會撞 UNIQUE）
        # 表名為本檔白名單常數（非外部輸入），以 f-string 內嵌識別字；值無外部輸入、無 injection 風險
        dupes = conn.execute(
            text(  # noqa: S608 — 識別字為本檔白名單常數，無使用者輸入
                f'SELECT lower("EMAIL") AS e, count(*) AS c FROM "{tbl}" '
                f'GROUP BY lower("EMAIL") HAVING count(*) > 1'
            )
        ).fetchall()
        if dupes:
            detail = ", ".join(f"{r.e}({r.c})" for r in dupes)
            raise RuntimeError(f'{tbl} 存在「僅大小寫不同」之重複 email，轉小寫會撞 UNIQUE，請先人工處理：{detail}')
        # 轉小寫（僅更新實際有大小寫差異的列）
        conn.execute(
            text(f'UPDATE "{tbl}" SET "EMAIL" = lower("EMAIL") WHERE "EMAIL" <> lower("EMAIL")')  # noqa: S608
        )


def downgrade() -> None:
    # 原始大小寫已遺失，無法還原；不實作
    pass