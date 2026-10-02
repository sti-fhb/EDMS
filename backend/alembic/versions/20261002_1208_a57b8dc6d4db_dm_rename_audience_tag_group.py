"""dm_rename_audience_tag_group

Revision ID: a57b8dc6d4db
Revises: cd1036ae3b75
Create Date: 2026-10-02 12:08:00.000000

`DM_TAG_GROUP` 之 AUDIENCE 組名由「可見對象」改為「職位」。

#437 把可見對象拆成（單位, 職位）兩個維度後，AUDIENCE 組實際存的就是職位（護理師 /
軍人 / 醫檢師…），但組名仍叫「可見對象」——與同層的「單位」並列時，看起來像是單位
不屬於可見對象。「可見對象」自此為**兩組的合稱**（DM 編輯頁與 DP 權限管理頁沿用此詞，
不在本次異動範圍）。

異動說明：
- 影響 Table：`DM_TAG_GROUP`（僅 1 列之 `TAG_GROUP_NAME`，不改 schema、不動標籤項）
- `TAG_GROUP_CODE` / `GROUP_TYPE` 皆不變，故**不影響任何判定邏輯**——程式一律以
  `AUDIENCE` 代碼或 `GROUP_TYPE` 比對，全庫無任何處比對組名字串（已 grep 確認）

條件帶原值（`WHERE TAG_GROUP_NAME = '可見對象'`）：組名目前無維護 UI，但若日後開放、
或有人直接改過 DB，不應被本 migration 蓋掉。downgrade 同理反向比對。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "a57b8dc6d4db"
down_revision: Union[str, None] = "cd1036ae3b75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GROUP_CODE = "AUDIENCE"
_OLD_NAME = "可見對象"
_NEW_NAME = "職位"

_RENAME = text(
    'UPDATE "DM_TAG_GROUP" SET "TAG_GROUP_NAME" = :new '
    'WHERE "TAG_GROUP_CODE" = :code AND "TAG_GROUP_NAME" = :old'
)


def upgrade() -> None:
    op.get_bind().execute(_RENAME.bindparams(new=_NEW_NAME, code=_GROUP_CODE, old=_OLD_NAME))


def downgrade() -> None:
    op.get_bind().execute(_RENAME.bindparams(new=_OLD_NAME, code=_GROUP_CODE, old=_NEW_NAME))
