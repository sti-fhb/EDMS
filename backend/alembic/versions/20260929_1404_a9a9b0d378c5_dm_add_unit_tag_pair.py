"""dm_add_unit_tag_pair

Revision ID: a9a9b0d378c5
Revises: 6f7bb0f23d38
Create Date: 2026-09-29 14:04:20.675680

可見對象改為（單位, 職位）配對，三表加 UNIT_TAG_ID。

異動說明（#437）：
- 影響 Table：DM_DOC_TAG、DM_VERSION_TAG、DM_USER_TAG（各加 `UNIT_TAG_ID`）、DM_TAG_GROUP、DM_TAG
- 唯一鍵各加 `UNIT_TAG_ID` 並宣告 **NULLS NOT DISTINCT**（PG 15+）——預設語意下 NULL ≠ NULL，
  檢索標籤列（`UNIT_TAG_ID IS NULL`）將不受唯一約束保護、可重複寫入同一筆而不報錯
- 新增標籤組 `UNIT`（`GROUP_TYPE='UNIT'`）+ 21 筆單位標籤（含通用值「全單位」）；
  `GROUP_TYPE` 不用 `AUDIENCE` 是為了讓既有 5 處依 `GROUP_TYPE` 分流的查詢自然排除單位，
  漏改之後果為「單位不出現」而非「單位被當成職位」
- `DM_TAG_GROUP.AUDIENCE` 之名稱由「可見對象/單位」改為「可見對象」（單位已分出為獨立組）
- 回填：`DM_DOC_TAG` / `DM_VERSION_TAG` 之 AUDIENCE 組列補上「全單位」，使既有文件可見範圍不變；
  `DM_USER_TAG` **不回填**（保持 NULL＝單位未指定），既有授權之可見範圍同樣不變
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "a9a9b0d378c5"
down_revision: Union[str, None] = "6f7bb0f23d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

_UNIT_GROUP_CODE = "UNIT"
_UNIT_GROUP_NAME = "單位"
_UNIT_GROUP_TYPE = "UNIT"

#: 單位組通用值——文件側掛此值代表「不限單位」；人側不得使用（人為具體單位或未指定）。
ALL_UNITS_TAG = "全單位"

#: 客戶提供之 20 個單位（2026-09-29），與 TBMS RUDP001 院區代碼對照表逐項核對一致。
_UNIT_TAGS = [
    ALL_UNITS_TAG,
    "國防部軍醫局",
    "國防醫學院三軍總醫院",
    "國軍高雄總醫院",
    "國軍臺中總醫院",
    "國軍桃園總醫院",
    "國軍花蓮總醫院",
    "國軍左營總醫院",
    "國防醫學院三軍總醫院松山分院",
    "國防醫學院三軍總醫院澎湖分院",
    "國防醫學院三軍總醫院基隆分院",
    "國防醫學院三軍總醫院北投分院",
    "國軍桃園總醫院新竹分院",
    "國軍左營總醫院岡山分院",
    "國軍高雄總醫院屏東分院",
    "國軍臺中總醫院中清分院",
    "國軍臺中總醫院捐血站",
    "國軍桃園總醫院捐血站",
    "國軍花蓮總醫院捐血站",
    "國軍左營總醫院捐血站",
    "國防醫學院三軍總醫院松山分院捐血站",
]

#: 回填 SQL（匯出供測試引用）：既有文件 / 版本之職位標籤補「全單位」，使可見範圍不變。
#: 僅動 AUDIENCE 組列——檢索標籤（RETRIEVAL 組）無單位維度，維持 NULL。
BACKFILL_DOC_TAG = (
    'UPDATE "DM_DOC_TAG" AS dt SET "UNIT_TAG_ID" = :all_units_id '
    'FROM "DM_TAG" AS t '
    'WHERE dt."TAG_ID" = t."TAG_ID" AND t."TAG_GROUP_CODE" = \'AUDIENCE\' AND dt."UNIT_TAG_ID" IS NULL'
)
BACKFILL_VERSION_TAG = (
    'UPDATE "DM_VERSION_TAG" AS vt SET "UNIT_TAG_ID" = :all_units_id '
    'FROM "DM_TAG" AS t '
    'WHERE vt."TAG_ID" = t."TAG_ID" AND t."TAG_GROUP_CODE" = \'AUDIENCE\' AND vt."UNIT_TAG_ID" IS NULL'
)


def upgrade() -> None:
    # ── 1. 三表加欄位、改唯一鍵（NULLS NOT DISTINCT）、加 FK ──
    op.add_column("DM_DOC_TAG", sa.Column("UNIT_TAG_ID", sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f("UQ_DM_DOC_TAG_DOC_TAG"), "DM_DOC_TAG", type_="unique")
    op.create_unique_constraint(
        "UQ_DM_DOC_TAG_DOC_TAG",
        "DM_DOC_TAG",
        ["DOC_ID", "TAG_ID", "UNIT_TAG_ID"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_foreign_key("FK_DM_DOC_TAG_UNIT", "DM_DOC_TAG", "DM_TAG", ["UNIT_TAG_ID"], ["TAG_ID"])

    op.add_column("DM_USER_TAG", sa.Column("UNIT_TAG_ID", sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f("UQ_DM_USER_TAG_USER_TAG"), "DM_USER_TAG", type_="unique")
    op.create_unique_constraint(
        "UQ_DM_USER_TAG_USER_TAG",
        "DM_USER_TAG",
        ["USER_ID", "TAG_ID", "UNIT_TAG_ID"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_foreign_key("FK_DM_USER_TAG_UNIT", "DM_USER_TAG", "DM_TAG", ["UNIT_TAG_ID"], ["TAG_ID"])

    op.add_column("DM_VERSION_TAG", sa.Column("UNIT_TAG_ID", sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f("UQ_DM_VERSION_TAG_VERSION_TAG"), "DM_VERSION_TAG", type_="unique")
    op.create_unique_constraint(
        "UQ_DM_VERSION_TAG_VERSION_TAG",
        "DM_VERSION_TAG",
        ["VERSION_ID", "TAG_ID", "UNIT_TAG_ID"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_foreign_key("FK_DM_VERSION_TAG_UNIT", "DM_VERSION_TAG", "DM_TAG", ["UNIT_TAG_ID"], ["TAG_ID"])

    # ── 2. seed UNIT 標籤組 + 21 筆單位 ──
    now = datetime.now(timezone.utc)
    conn = op.get_bind()
    conn.execute(
        text(
            'INSERT INTO "DM_TAG_GROUP" ("TAG_GROUP_CODE", "TAG_GROUP_NAME", "GROUP_TYPE", "IS_BUILTIN", '
            '"CREATED_USER", "CREATED_DATE", "DELETED") '
            "VALUES (:code, :name, :gtype, true, :u, :d, 0) "
            'ON CONFLICT ("TAG_GROUP_CODE") DO NOTHING'
        ),
        {
            "code": _UNIT_GROUP_CODE,
            "name": _UNIT_GROUP_NAME,
            "gtype": _UNIT_GROUP_TYPE,
            "u": _SEED_USER,
            "d": now,
        },
    )
    for tag_name in _UNIT_TAGS:
        conn.execute(
            text(
                'INSERT INTO "DM_TAG" ("TAG_GROUP_CODE", "TAG_NAME", "IS_ENABLED", "CREATED_USER", "CREATED_DATE", '
                '"DELETED") '
                "SELECT 'UNIT', :name_val, true, :u, :d, 0 "
                "WHERE NOT EXISTS ("
                'SELECT 1 FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = \'UNIT\' AND "TAG_NAME" = :name_chk)'
            ),
            {"name_val": tag_name, "name_chk": tag_name, "u": _SEED_USER, "d": now},
        )

    # ── 3. 組內標籤名稱唯一（#437 安全前提）──
    # `visibility.audience_pair_match` 以 TAG_NAME 辨識「全單位」/「全體」兩個通用值。組內若可
    # 出現同名標籤，把某個具體單位改名為「全單位」即等於讓所有掛該單位的文件對全體閱覽者開放，
    # 而稽核只會留下一筆「改名」。DM 尚未上線正式環境（現有 DB 皆由 migration 從頭建），seed 之
    # 各組名稱本即唯一，故不需先清重複。
    op.create_unique_constraint("UQ_DM_TAG_GROUP_NAME", "DM_TAG", ["TAG_GROUP_CODE", "TAG_NAME"])

    # ── 4. AUDIENCE 組更名（單位已分出為獨立組）──
    conn.execute(
        text('UPDATE "DM_TAG_GROUP" SET "TAG_GROUP_NAME" = :name WHERE "TAG_GROUP_CODE" = \'AUDIENCE\''),
        {"name": "可見對象"},
    )

    # ── 5. 回填：既有文件 / 版本之職位標籤補「全單位」，可見範圍不變 ──
    all_units_id = conn.execute(
        text('SELECT "TAG_ID" FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = \'UNIT\' AND "TAG_NAME" = :name'),
        {"name": ALL_UNITS_TAG},
    ).scalar_one()
    conn.execute(text(BACKFILL_DOC_TAG), {"all_units_id": all_units_id})
    conn.execute(text(BACKFILL_VERSION_TAG), {"all_units_id": all_units_id})
    # DM_USER_TAG 不回填：保持 NULL＝單位未指定，僅能匹配文件側之「全單位」，既有可見範圍不變。


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text('UPDATE "DM_TAG_GROUP" SET "TAG_GROUP_NAME" = :name WHERE "TAG_GROUP_CODE" = \'AUDIENCE\''),
        {"name": "可見對象/單位"},
    )
    # ⚠️ 刪 seed 必須排在三張表之 UNIT_TAG_ID 欄位 drop **之後**（見本函式末）：upgrade 的回填讓
    # 每一筆 AUDIENCE 文件標籤列都指向「全單位」，此時刪標籤會撞 FK_DM_*_UNIT。順序寫反會讓任何
    # 有資料的 DB 無法 rollback，而空 DB（測試環境）完全測不出來。

    op.drop_constraint("UQ_DM_TAG_GROUP_NAME", "DM_TAG", type_="unique")

    op.drop_constraint("FK_DM_VERSION_TAG_UNIT", "DM_VERSION_TAG", type_="foreignkey")
    op.drop_constraint("UQ_DM_VERSION_TAG_VERSION_TAG", "DM_VERSION_TAG", type_="unique")
    op.create_unique_constraint(
        op.f("UQ_DM_VERSION_TAG_VERSION_TAG"),
        "DM_VERSION_TAG",
        ["VERSION_ID", "TAG_ID"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("DM_VERSION_TAG", "UNIT_TAG_ID")

    op.drop_constraint("FK_DM_USER_TAG_UNIT", "DM_USER_TAG", type_="foreignkey")
    op.drop_constraint("UQ_DM_USER_TAG_USER_TAG", "DM_USER_TAG", type_="unique")
    op.create_unique_constraint(
        op.f("UQ_DM_USER_TAG_USER_TAG"),
        "DM_USER_TAG",
        ["USER_ID", "TAG_ID"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("DM_USER_TAG", "UNIT_TAG_ID")

    op.drop_constraint("FK_DM_DOC_TAG_UNIT", "DM_DOC_TAG", type_="foreignkey")
    op.drop_constraint("UQ_DM_DOC_TAG_DOC_TAG", "DM_DOC_TAG", type_="unique")
    op.create_unique_constraint(
        op.f("UQ_DM_DOC_TAG_DOC_TAG"),
        "DM_DOC_TAG",
        ["DOC_ID", "TAG_ID"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("DM_DOC_TAG", "UNIT_TAG_ID")

    # 三張表之 UNIT_TAG_ID 皆已移除、FK 不復存在，此時才能刪 seed（見上方順序說明）。
    # 硬刪除為 seed 清理之例外（非業務資料，且本組於 downgrade 後不應殘留）。
    conn.execute(text('DELETE FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = \'UNIT\''))
    conn.execute(text('DELETE FROM "DM_TAG_GROUP" WHERE "TAG_GROUP_CODE" = \'UNIT\''))
