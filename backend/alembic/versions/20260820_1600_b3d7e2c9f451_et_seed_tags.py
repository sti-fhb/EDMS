"""et_seed_tags

Revision ID: b3d7e2c9f451
Revises: 9aa92b82d0a0
Create Date: 2026-08-20 16:00:00.000000

ET 受訓單位標籤庫種子（#185，T022）——5 筆內建標籤，依 docs/specs/et/data-model.md
§受訓單位標籤（ET_TAG）。

「全體」為系統內建**特殊標籤**（`IS_ALL=true`）：代表所有具「學員」角色之使用者，
不需逐人貼標；**不可停用、不可改名**（於受控主檔轉接層 SRVET004 伺服器端拒絕，
error_code `ET_TAG_001`）。全系統僅此 1 筆 `IS_ALL=true`。

冪等：以 `WHERE NOT EXISTS` 依 `TAG_NAME` 判重（`TAG_ID` 為 Identity 自動配號，
無法用 ON CONFLICT 指定），重跑不重複、不覆寫管理者後續編輯之 `IS_ACTIVE` /
`DISPLAY_ORDER`。比照 `dm_seed_business_data` 之 `_AUDIENCE_TAGS` 寫法。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "b3d7e2c9f451"
down_revision: Union[str, None] = "9aa92b82d0a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

# (TAG_NAME, IS_ALL, DISPLAY_ORDER)；全部 IS_BUILTIN=true、IS_ACTIVE=true
_TAGS: list[tuple[str, bool, int]] = [
    ("全體", True, 1),
    ("護理師", False, 2),
    ("行政人員", False, 3),
    ("軍人", False, 4),
    ("醫檢師", False, 5),
]


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for tag_name, is_all, order in _TAGS:
        conn.execute(
            text(
                'INSERT INTO "ET_TAG" ("TAG_NAME", "IS_ACTIVE", "IS_ALL", "IS_BUILTIN", "DISPLAY_ORDER", '
                '"CREATED_USER", "CREATED_DATE", "DELETED") '
                "SELECT :name_val, true, :is_all, true, :order, :u, :d, 0 "
                'WHERE NOT EXISTS (SELECT 1 FROM "ET_TAG" WHERE "TAG_NAME" = :name_chk)'
            ),
            {
                "name_val": tag_name,
                "name_chk": tag_name,
                "is_all": is_all,
                "order": order,
                "u": _SEED_USER,
                "d": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text('DELETE FROM "ET_TAG" WHERE "TAG_NAME" = ANY(:names)'),
        {"names": [t[0] for t in _TAGS]},
    )
