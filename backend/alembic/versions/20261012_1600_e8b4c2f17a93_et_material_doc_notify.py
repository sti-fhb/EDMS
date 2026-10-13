"""et_material_doc_notify

Revision ID: e8b4c2f17a93
Revises: 15e30a8f8b6f
Create Date: 2026-10-12 16:00:00.000000

引用之 DM 文件改版 / 廢止時通知課程擁有者（#231）。

異動說明：
- 新增 Table `ET_MATERIAL_DOC_NOTIFY`：通知簿記，記「上次通知某位擁有者時，該文件是
  哪一版、什麼狀態」。唯一鍵 `(DOC_ID, OWNER_ID)`
- `DP_NOTIFY_TEMPLATE`（`MODULE='ET'`）新增 2 類範本：`DOC_VERSION_CHANGED`（改版）
  與 `DOC_OBSOLETED`（廢止）。ET 可維護範本由 **8 類增為 10 類**

## ⛔ 本表不回填（#231 裁示 Q1 = C）

正式環境之資料庫由空的 migration 從頭建起，本 migration 執行當下 `ET_MATERIAL_DOC`
為空、沒有任何引用，故 A（migration 回填）/ B（首次只寫不寄）/ C（不回填）三者在正式
環境完全等價，選最單純的 C——不寫只為了不存在的情境而設的特例程式碼。

⚠️ 副作用只在既有資料的測試環境：首次排程會對既有引用各寄一封，視為該通知路徑的
端對端實測。

## 為何兩個範本而不是一個

兩者的**處置不同**：改版是「去確認測驗題還對不對」（學員已經在讀新內容），廢止是
「移除引用或換一份，否則這門課再發布會被 `BLOCK_OBSOLETE_DOC` 擋下」。合成一封帶
狀態欄位的通用信，教師讀不出該做哪件事。

⚠️ **`VARIABLES` 必須與 `BODY` / `SUBJECT` 的佔位逐字一致**。平台 `_SafeFormatter`
在 params key 對不上時會 KeyError → 寄出空信並記 FAILED、`queued_count=0` 且**不外拋**
——症狀是「信沒到但程式沒錯」。此處變數名與 `et/notify/doc_changed.py` 的 params 是
同一組字面量，改任一邊都要同步。

⚠️ `CHANNEL` 只能用平台正規詞彙（`EMAIL` / `MSG` / `BOTH`）——自創值會使平台
`send_email` 靜默不寄信。此處為 `EMAIL`：平台**沒有站內訊息佇列**（見 #554），而課程
擁有者在 ET 沒有任何畫面會呈現「引用的文件變了」，設 `MSG` 等於不送。

`IS_SYSTEM=false`：#231 裁示 Q4 = A，兩類比照既有 8 類由 ET 管理者於 DP 後台編輯與
啟停。已知且接受的後果是管理者可停用廢止警告（與既有 8 類的停用語意一致）。
"""

# ruff: noqa: S608
# S608 說明：`_seed()` 以 f-string 組出 INSERT 骨架，但代入的表名與欄位名皆為本檔內
# 之常數字面量（非外部輸入），實際「值」一律走 bindparams 參數化——無注入面。
# 比照 #185 / #361 同一寫法與同一豁免。

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "e8b4c2f17a93"
down_revision: Union[str, None] = "15e30a8f8b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# (MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION)
_TEMPLATES: list[tuple] = [
    (
        "ET",
        "DOC_VERSION_CHANGED",
        "引用文件改版通知",
        "【教育訓練】訓練教材「{DOC_NAME}」已更新版本，請確認測驗內容",
        "{USER_NAME} 您好：\n\n您課程引用的訓練教材文件已發布新版本，學員開啟章節時"
        "即會看到新內容。\n\n"
        "文件編號：{DOC_ID}\n"
        "文件名稱：{DOC_NAME}\n"
        "目前版本：{VERSION_NO}\n"
        "受影響課程：{COURSE_LIST}\n\n"
        "⚠️ 若該文件的內容有異動，依舊版內容出的測驗題可能已對不上——學員會讀到新內容"
        "卻被舊答案判錯。請確認上列課程的測驗題仍然正確。\n"
        "課程管理：{COURSE_URL}" + _FOOTER,
        "USER_NAME,DOC_ID,DOC_NAME,VERSION_NO,COURSE_LIST,COURSE_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "DOC_OBSOLETED",
        "引用文件廢止通知",
        "【教育訓練】訓練教材「{DOC_NAME}」已廢止，請移除引用",
        "{USER_NAME} 您好：\n\n您課程引用的訓練教材文件已被廢止。\n\n"
        "文件編號：{DOC_ID}\n"
        "文件名稱：{DOC_NAME}\n"
        "受影響課程：{COURSE_LIST}\n\n"
        "⚠️ 上列課程在**再次發布或再開課**時會因引用已廢止文件而被擋下。請移除該文件的"
        "引用，或改引用其他文件。\n"
        "課程管理：{COURSE_URL}" + _FOOTER,
        "USER_NAME,DOC_ID,DOC_NAME,COURSE_LIST,COURSE_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
]


def _seed(table: str, biz_cols: list[str], pk_cols: list[str], rows: list[tuple], now: datetime) -> None:
    """參數化 INSERT + ON CONFLICT DO NOTHING（附標準欄位）。比照 #185 / #361 之 _seed。"""
    all_cols = [*biz_cols, "CREATED_USER", "CREATED_DATE", "DELETED"]
    col_sql = ", ".join(f'"{c}"' for c in all_cols)
    ph_sql = ", ".join(f":{c}" for c in all_cols)
    conflict_sql = ", ".join(f'"{c}"' for c in pk_cols)
    stmt = text(f'INSERT INTO "{table}" ({col_sql}) VALUES ({ph_sql}) ON CONFLICT ({conflict_sql}) DO NOTHING')
    for row in rows:
        params = dict(zip(biz_cols, row, strict=True))
        params["CREATED_USER"] = _SEED_USER
        params["CREATED_DATE"] = now
        params["DELETED"] = 0
        op.execute(stmt.bindparams(**params))


def upgrade() -> None:
    op.create_table(
        "ET_MATERIAL_DOC_NOTIFY",
        sa.Column("NOTIFY_ID", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("DOC_ID", sa.String(length=20), nullable=False),
        sa.Column("OWNER_ID", sa.String(length=20), nullable=False),
        sa.Column("LAST_NOTIFIED_VERSION_ID", sa.Integer(), nullable=False),
        sa.Column("LAST_NOTIFIED_STATUS", sa.String(length=20), nullable=False),
        sa.Column("CREATED_USER", sa.String(length=20), nullable=False),
        sa.Column("CREATED_DATE", sa.DateTime(timezone=True), nullable=False),
        sa.Column("UPDATED_USER", sa.String(length=20), nullable=True),
        sa.Column("UPDATED_DATE", sa.DateTime(timezone=True), nullable=True),
        sa.Column("DELETED", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("NOTIFY_ID", name="PK_ET_MATERIAL_DOC_NOTIFY"),
    )
    # 全表唯一（非部分索引）：本表不軟刪除，不會有「已刪除列佔住鍵」的問題。
    op.create_index(
        "UX_ET_MATERIAL_DOC_NOTIFY_DOC_OWNER",
        "ET_MATERIAL_DOC_NOTIFY",
        ["DOC_ID", "OWNER_ID"],
        unique=True,
    )
    _seed(
        "DP_NOTIFY_TEMPLATE",
        [
            "MODULE",
            "TEMPLATE_CODE",
            "TEMPLATE_NAME",
            "SUBJECT",
            "BODY",
            "VARIABLES",
            "CHANNEL",
            "IS_ENABLED",
            "IS_SYSTEM",
            "VERSION",
        ],
        ["MODULE", "TEMPLATE_CODE"],
        _TEMPLATES,
        datetime.now(timezone.utc),
    )


def downgrade() -> None:
    """精確刪除本 migration 所種之列（比對 PK），再移除本表。

    不用寬鬆的 `MODULE='ET'` 範圍刪除——避免誤刪日後管理者於 DP 後台新增之列
    （對齊 #185 / #361 與 DM #127 之精確 downgrade 慣例）。
    """
    conn = op.get_bind()
    for module, template_code, *_ in _TEMPLATES:
        conn.execute(
            text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c').bindparams(
                m=module, c=template_code
            )
        )
    op.drop_index("UX_ET_MATERIAL_DOC_NOTIFY_DOC_OWNER", table_name="ET_MATERIAL_DOC_NOTIFY")
    op.drop_table("ET_MATERIAL_DOC_NOTIFY")
