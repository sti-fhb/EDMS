"""dm_seed_business_data

Revision ID: 071cc687bea9
Revises: 6a061732e842
Create Date: 2026-08-06 11:08:44.777962

DM 業務種子（DM 自有表）：
- DM_CATEGORY：4 內建分類（SOP / MANUAL / TRAINING / OTHER，IS_BUILTIN=true、代碼鎖定）
- DM_TAG_GROUP：4 內建組（AUDIENCE〔權限〕/ MODULE / NATURE / LEGAL〔檢索〕）
- DM_TAG：AUDIENCE 組 5 個可見對象預設值（全體 / 護理師 / 軍人 / 醫檢師 / 行政人員）

全部參數化 INSERT + idempotent（分類 / 標籤組以 PK ON CONFLICT DO NOTHING；標籤以
(TAG_GROUP_CODE, TAG_NAME) NOT EXISTS 防重）。DM 通知範本 / DM_ 參數種子另於後續 migration
寫入平台 DP 共用表（依 TBMS 前例：各模組 migration 種自己前綴 / MODULE 之列）。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "071cc687bea9"
down_revision: Union[str, None] = "6a061732e842"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

# (CATEGORY_CODE, CATEGORY_NAME)
_CATEGORIES = [
    ("SOP", "標準作業程序"),
    ("MANUAL", "系統操作手冊"),
    ("TRAINING", "訓練教材"),
    ("OTHER", "其他"),
]

# (TAG_GROUP_CODE, TAG_GROUP_NAME, GROUP_TYPE)
_TAG_GROUPS = [
    ("AUDIENCE", "可見對象/單位", "AUDIENCE"),
    ("MODULE", "適用模組", "RETRIEVAL"),
    ("NATURE", "文件性質", "RETRIEVAL"),
    ("LEGAL", "法規關聯", "RETRIEVAL"),
]

# AUDIENCE 組可見對象預設值
_AUDIENCE_TAGS = ["全體", "護理師", "軍人", "醫檢師", "行政人員"]


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    conn = op.get_bind()

    for code, name in _CATEGORIES:
        conn.execute(
            text(
                'INSERT INTO "DM_CATEGORY" ("CATEGORY_CODE", "CATEGORY_NAME", "IS_BUILTIN", "IS_ENABLED", '
                '"CREATED_USER", "CREATED_DATE", "DELETED") '
                "VALUES (:code, :name, true, true, :u, :d, 0) "
                'ON CONFLICT ("CATEGORY_CODE") DO NOTHING'
            ),
            {"code": code, "name": name, "u": _SEED_USER, "d": now},
        )

    for code, name, gtype in _TAG_GROUPS:
        conn.execute(
            text(
                'INSERT INTO "DM_TAG_GROUP" ("TAG_GROUP_CODE", "TAG_GROUP_NAME", "GROUP_TYPE", "IS_BUILTIN", '
                '"CREATED_USER", "CREATED_DATE", "DELETED") '
                "VALUES (:code, :name, :gtype, true, :u, :d, 0) "
                'ON CONFLICT ("TAG_GROUP_CODE") DO NOTHING'
            ),
            {"code": code, "name": name, "gtype": gtype, "u": _SEED_USER, "d": now},
        )

    for tag_name in _AUDIENCE_TAGS:
        conn.execute(
            text(
                'INSERT INTO "DM_TAG" ("TAG_GROUP_CODE", "TAG_NAME", "IS_ENABLED", "CREATED_USER", "CREATED_DATE", '
                '"DELETED") '
                "SELECT 'AUDIENCE', :name_val, true, :u, :d, 0 "
                "WHERE NOT EXISTS ("
                'SELECT 1 FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = \'AUDIENCE\' AND "TAG_NAME" = :name_chk)'
            ),
            {"name_val": tag_name, "name_chk": tag_name, "u": _SEED_USER, "d": now},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text('DELETE FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = \'AUDIENCE\' AND "TAG_NAME" = ANY(:names)'),
        {"names": _AUDIENCE_TAGS},
    )
    conn.execute(
        text('DELETE FROM "DM_TAG_GROUP" WHERE "TAG_GROUP_CODE" = ANY(:codes)'),
        {"codes": [g[0] for g in _TAG_GROUPS]},
    )
    conn.execute(
        text('DELETE FROM "DM_CATEGORY" WHERE "CATEGORY_CODE" = ANY(:codes)'),
        {"codes": [c[0] for c in _CATEGORIES]},
    )
