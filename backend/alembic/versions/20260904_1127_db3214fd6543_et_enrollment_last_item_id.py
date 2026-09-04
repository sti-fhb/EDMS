r"""ET_ENROLLMENT 增 LAST_ITEM_ID：學員上次檢視之章節項目（#274 SA Q1 裁示 B）。

## 為什麼需要這個欄位

`spec_us5` AC 3 / FR-ET-US5-02 要求「重新進入課程時定位至上次觀看位置」，並註明
「依 `ET_PROGRESS` 之 `LAST_POSITION`」——但**該欄位已於 2026-08-19 移至
`ET_PROGRESS_VIDEO`**（`data-model` 記載了那次搬移，理由是同一教材含多支影片時
無法分別記錄）。

搬移之後：

- `ET_PROGRESS`：只有 `IS_COMPLETED`——**沒有欄位能表達「上次看到哪個項目」**
- `ET_PROGRESS_VIDEO.LAST_POSITION_SEC`：只是**單支影片內**的秒數

於是定位所需的兩段資訊只剩一段。本 migration 補上另一段。

## 為何放在 ET_ENROLLMENT 而非 ET_PROGRESS

`ET_PROGRESS` 是**項目層**（一人一項目一列），「上次看的是哪一項」天然是**課程層**
的單一值（一人一課一列）——放在項目層等於還要額外定義「哪一列才算數」。

`ET_ENROLLMENT` 原本已有 `LAST_ACTIVITY_AT`（最後活動**時間**）卻沒有「最後活動在
**哪**」，補上這欄正好讓那對欄位完整。

## nullable 且不回填

既有選課列沒有這個值就是「還沒看過」，前端定位至第 1 章第 1 項（即現行行為）。
回填沒有意義——我們無從得知歷史上他最後看的是哪一項。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "db3214fd6543"
down_revision: str | Sequence[str] | None = "9eb4dd6e496b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ET_ENROLLMENT", sa.Column("LAST_ITEM_ID", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "FK_ET_ENROLLMENT_LAST_ITEM",
        "ET_ENROLLMENT",
        "ET_ITEM",
        ["LAST_ITEM_ID"],
        ["ITEM_ID"],
    )


def downgrade() -> None:
    """可逆——欄位為 nullable 且不參與任何唯一約束，移除不影響既有資料。

    移除後「上次檢視項目」會回到「定位第 1 章第 1 項」，屬功能降級而非資料損失
    （影片內的秒數仍存於 `ET_PROGRESS_VIDEO`）。
    """
    op.drop_constraint("FK_ET_ENROLLMENT_LAST_ITEM", "ET_ENROLLMENT", type_="foreignkey")
    op.drop_column("ET_ENROLLMENT", "LAST_ITEM_ID")
