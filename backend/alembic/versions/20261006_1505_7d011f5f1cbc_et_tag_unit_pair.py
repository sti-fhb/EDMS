"""et_tag_unit_pair

Revision ID: 7d011f5f1cbc
Revises: b4e7c9a1d2f3
Create Date: 2026-10-06 15:05:51.490602

受訓對象（原「受訓單位標籤」）改為（單位, 職位）配對（#538，比照 DM #437）。

異動說明：
- 影響 Table：ET_TAG（加 `TAG_TYPE`）、ET_COURSE_TAG / ET_USER_TAG（各加 `UNIT_TAG_ID`）
- `ET_TAG.TAG_TYPE`：`AUDIENCE`（職位，既有 5 筆）/ `UNIT`（單位，本次 seed 21 筆）。值刻意與 DM
  之 `GROUP_TYPE` 相同——DP02 權限管理以 `kind == "UNIT"` 判定是否走配對模式
- `IS_ALL` 由「全系統 1 筆」改為「**每個 `TAG_TYPE` 1 筆**」：職位的「全體」、單位的「全單位」。
  ⭐ 通用值一律以 `IS_ALL` 判定、**不以名稱判定**——DM 以 `TAG_NAME` 辨識「全單位」，改名即擴權
  （#437 follow-up 1）；ET 本來就有旗標，擴到單位維度即可一次避開
- 單位清單**複製 DM 那支 migration（`a9a9b0d378c5`）的 seed**，逐字照抄名稱與順序（#538 SA Q1
  裁示：只對齊這一次，之後兩邊各自維護）。⛔ 不讀 `DM_TAG`：跨模組讀表違反模組邊界
- `ET_COURSE_TAG.UNIT_TAG_ID` 回填後改 **NOT NULL**：課程端兩欄必填，讓 DB 直接擋掉半組配對
- `ET_USER_TAG.UNIT_TAG_ID` **保持 nullable、不回填**（NULL＝單位未指定，僅匹配課程端「全單位」）
- 兩張表的唯一鍵各加 `UNIT_TAG_ID`，並宣告 **NULLS NOT DISTINCT**——預設語意下 NULL ≠ NULL，
  單位未指定的使用者列將不受唯一約束保護、可重複寫入同一筆
- ⚠️ **不動 `ET_ENROLLMENT` 的唯一鍵**：標籤帶入的 `ON CONFLICT DO NOTHING` 吃的是它，那是「被移除的
  學員不會被標籤帶回來」的實作方式（#247 SA Q1 裁示 C）
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "7d011f5f1cbc"
down_revision: Union[str, None] = "b4e7c9a1d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
TAG_TYPE_UNIT = "UNIT"
TAG_TYPE_AUDIENCE = "AUDIENCE"

#: 單位組通用值——課程端掛此值代表「不限單位」；人身上不會掛它（人為具體單位或未指定）。
ALL_UNITS_TAG = "全單位"

#: 逐字複製自 DM `a9a9b0d378c5_dm_add_unit_tag_pair._UNIT_TAGS`（#538 SA Q1：只對齊這一次）。
UNIT_TAGS = [
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

#: 回填 SQL（匯出供測試引用）：既有課程標籤補「全單位」，使帶入範圍不變。
BACKFILL_COURSE_TAG = 'UPDATE "ET_COURSE_TAG" SET "UNIT_TAG_ID" = :all_units_id WHERE "UNIT_TAG_ID" IS NULL'


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # ── 1. ET_TAG 加類型；IS_ALL 改為每類一筆 ──
    op.add_column(
        "ET_TAG",
        sa.Column("TAG_TYPE", sa.String(10), nullable=False, server_default=TAG_TYPE_AUDIENCE),
    )
    op.create_index(
        "UX_ET_TAG_TYPE_ALL",
        "ET_TAG",
        ["TAG_TYPE"],
        unique=True,
        postgresql_where=sa.text('"IS_ALL"'),
    )

    # ── 2. seed 21 筆單位（「全單位」為 IS_ALL）──
    # 冪等：以 `WHERE NOT EXISTS` 依 `TAG_NAME` 判重（`UQ_ET_TAG_NAME` 為全表唯一），比照 `et_seed_tags`。
    #
    # ⚠️ 判重前先擋**撞名**：本 migration 之前 ET_TAG 只有職位，若管理者在 DP03 建過一個名稱與單位
    # 相同的職位標籤，`NOT EXISTS` 會讓該單位被**靜默略過**——它從此不在單位清單裡，而沒有任何錯誤；
    # 撞到的若是「全單位」，下方 `scalar_one()` 會在升級途中炸掉。空 DB 與測試 DB 都測不出來，
    # 故在這裡明確中止並列出撞名，由人決定改哪一邊的名稱。
    collisions = conn.execute(
        text('SELECT "TAG_NAME" FROM "ET_TAG" WHERE "TAG_TYPE" <> :t AND "TAG_NAME" = ANY(:names)'),
        {"t": TAG_TYPE_UNIT, "names": UNIT_TAGS},
    ).scalars().all()
    if collisions:
        raise RuntimeError(f"ET_TAG 已有與單位同名的非單位標籤，請先改名後再升級：{sorted(collisions)}")
    for order, tag_name in enumerate(UNIT_TAGS, start=1):
        conn.execute(
            text(
                'INSERT INTO "ET_TAG" ("TAG_NAME", "TAG_TYPE", "IS_ACTIVE", "IS_ALL", "IS_BUILTIN", "DISPLAY_ORDER", '
                '"CREATED_USER", "CREATED_DATE", "DELETED") '
                "SELECT :name_val, :tag_type, true, :is_all, true, :order, :u, :d, 0 "
                'WHERE NOT EXISTS (SELECT 1 FROM "ET_TAG" WHERE "TAG_NAME" = :name_chk)'
            ),
            {
                "name_val": tag_name,
                "name_chk": tag_name,
                "tag_type": TAG_TYPE_UNIT,
                "is_all": tag_name == ALL_UNITS_TAG,
                "order": order,
                "u": _SEED_USER,
                "d": now,
            },
        )
    all_units_id = conn.execute(
        text('SELECT "TAG_ID" FROM "ET_TAG" WHERE "TAG_TYPE" = :t AND "IS_ALL"'),
        {"t": TAG_TYPE_UNIT},
    ).scalar_one()

    # ── 3. ET_COURSE_TAG：加欄位 → 回填「全單位」→ NOT NULL → 換唯一鍵 ──
    op.add_column("ET_COURSE_TAG", sa.Column("UNIT_TAG_ID", sa.BigInteger(), nullable=True))
    conn.execute(text(BACKFILL_COURSE_TAG), {"all_units_id": all_units_id})
    op.alter_column("ET_COURSE_TAG", "UNIT_TAG_ID", nullable=False)
    op.create_foreign_key("FK_ET_COURSE_TAG_UNIT", "ET_COURSE_TAG", "ET_TAG", ["UNIT_TAG_ID"], ["TAG_ID"])
    op.drop_constraint("UQ_ET_COURSE_TAG_COURSE_TAG", "ET_COURSE_TAG", type_="unique")
    op.create_unique_constraint(
        "UQ_ET_COURSE_TAG_COURSE_TAG",
        "ET_COURSE_TAG",
        ["COURSE_ID", "TAG_ID", "UNIT_TAG_ID"],
        postgresql_nulls_not_distinct=True,
    )

    # ── 4. ET_USER_TAG：加欄位（nullable、不回填）→ 換唯一鍵 ──
    op.add_column("ET_USER_TAG", sa.Column("UNIT_TAG_ID", sa.BigInteger(), nullable=True))
    op.create_foreign_key("FK_ET_USER_TAG_UNIT", "ET_USER_TAG", "ET_TAG", ["UNIT_TAG_ID"], ["TAG_ID"])
    op.drop_constraint("UQ_ET_USER_TAG_USER_TAG", "ET_USER_TAG", type_="unique")
    op.create_unique_constraint(
        "UQ_ET_USER_TAG_USER_TAG",
        "ET_USER_TAG",
        ["USER_ID", "TAG_ID", "UNIT_TAG_ID"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    conn = op.get_bind()

    # 🔴 **有指定單位的課程配對時中止**（security review MEDIUM）。降版後只剩職位欄，回到「職位 =
    # 全部具該職位者」的舊語意：`(三總, 護理師)` 會變成全院護理師、`(三總, 全體)` 會變成**全部學員**。
    # 之後一發布、或管理者一貼標，範圍外的人就會被加進課程並收到通知信——這不只是「丟失單位資訊」，
    # 是範圍擴大。只有當所有現役課程配對都是「全單位」時，降版才與升版前的語意相同。
    # 使用者端不必檢查：課程端全是「全單位」時，使用者配對的單位本來就不影響匹配結果。
    widened = conn.execute(
        text(
            'SELECT COUNT(*) FROM "ET_COURSE_TAG" ct JOIN "ET_TAG" u ON u."TAG_ID" = ct."UNIT_TAG_ID" '
            'WHERE ct."DELETED" = 0 AND NOT u."IS_ALL"'
        )
    ).scalar_one()
    if widened:
        raise RuntimeError(
            f"有 {widened} 組課程受訓對象指定了單位，降版會使其擴大為全部單位（並可能自動帶入範圍外學員），中止降版"
        )

    # ⚠️ 刪 seed 必須排在兩張表的 UNIT_TAG_ID 欄位 drop **之後**：upgrade 的回填讓每一筆課程標籤都
    # 指向「全單位」，此時刪標籤會撞 FK_ET_*_UNIT。順序寫反會讓任何有資料的 DB 無法 rollback，
    # 而空 DB（測試環境）完全測不出來（#437 的 security review MEDIUM）。
    #
    # ⚠️ 降版會**丟失單位資訊**：同一門課若掛了 (三總, 護理師) 與 (松山, 護理師)，降回單一維度後
    # 兩列會撞舊唯一鍵 `(COURSE_ID, TAG_ID)`。先刪掉多餘的列——每組 (COURSE_ID, TAG_ID) 留**現役優先、
    # 再取最小 PK** 的那一列。只比 PK 的話，「已軟刪的舊配對（PK 小）+ 現役配對（PK 大）」會留下已刪的那列、
    # 刪掉現役的那列，降版後這個人的指派就不見了（code review MEDIUM）。比較 `(DELETED, PK)`：0 < 1，
    # 有現役列時一定留現役列。
    conn.execute(
        text(
            'DELETE FROM "ET_USER_TAG" a USING "ET_USER_TAG" b '
            'WHERE a."USER_ID" = b."USER_ID" AND a."TAG_ID" = b."TAG_ID" '
            'AND (a."DELETED", a."USER_TAG_ID") > (b."DELETED", b."USER_TAG_ID")'
        )
    )
    op.drop_constraint("UQ_ET_USER_TAG_USER_TAG", "ET_USER_TAG", type_="unique")
    op.create_unique_constraint("UQ_ET_USER_TAG_USER_TAG", "ET_USER_TAG", ["USER_ID", "TAG_ID"])
    op.drop_constraint("FK_ET_USER_TAG_UNIT", "ET_USER_TAG", type_="foreignkey")
    op.drop_column("ET_USER_TAG", "UNIT_TAG_ID")

    conn.execute(
        text(
            'DELETE FROM "ET_COURSE_TAG" a USING "ET_COURSE_TAG" b '
            'WHERE a."COURSE_ID" = b."COURSE_ID" AND a."TAG_ID" = b."TAG_ID" '
            'AND (a."DELETED", a."COURSE_TAG_ID") > (b."DELETED", b."COURSE_TAG_ID")'
        )
    )
    op.drop_constraint("UQ_ET_COURSE_TAG_COURSE_TAG", "ET_COURSE_TAG", type_="unique")
    op.create_unique_constraint("UQ_ET_COURSE_TAG_COURSE_TAG", "ET_COURSE_TAG", ["COURSE_ID", "TAG_ID"])
    op.drop_constraint("FK_ET_COURSE_TAG_UNIT", "ET_COURSE_TAG", type_="foreignkey")
    op.drop_column("ET_COURSE_TAG", "UNIT_TAG_ID")

    # 兩張表之 UNIT_TAG_ID 皆已移除、FK 不復存在，此時才能刪 seed。硬刪除為 seed 清理之例外。
    conn.execute(text('DELETE FROM "ET_TAG" WHERE "TAG_TYPE" = :t'), {"t": TAG_TYPE_UNIT})
    op.drop_index("UX_ET_TAG_TYPE_ALL", table_name="ET_TAG")
    op.drop_column("ET_TAG", "TAG_TYPE")
