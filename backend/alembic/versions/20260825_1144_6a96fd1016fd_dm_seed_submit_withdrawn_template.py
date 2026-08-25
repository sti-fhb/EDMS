"""dm_seed_submit_withdrawn_template

Revision ID: 6a96fd1016fd
Revises: d5f9a2b8e614
Create Date: 2026-08-25 11:44:32.247533

US9（個人專區）新增 DM 通知範本 `SUBMIT_WITHDRAWN`（撰寫者撤回送審 / 廢止申請時，以站內訊息通知原指派
審核者）。CHANNEL 沿用平台正規詞彙 `MSG`（僅站內、不寄 Email，同 AUTO_REMIND）；先驗後插 ON CONFLICT
DO NOTHING（比照 b7fa4b6e4fe7）。IS_SYSTEM=false（可停用、事件固定）。

"""

# ruff: noqa: S608
from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "6a96fd1016fd"
down_revision: Union[str, None] = "d5f9a2b8e614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# (MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION)
_TEMPLATE = (
    "DM",
    "SUBMIT_WITHDRAWN",
    "送審撤回通知",
    "【送審撤回】{doc_name} 送審已撤回",
    "{reviewer_name} 您好：\n\n{author_name} 已撤回文件「{doc_name}」之送審，該項目無需您處理。" + _FOOTER,
    "reviewer_name,author_name,doc_name",
    "MSG",
    True,
    False,
    1,
)

_BIZ_COLS = [
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
]


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    all_cols = [*_BIZ_COLS, "CREATED_USER", "CREATED_DATE", "DELETED"]
    col_sql = ", ".join(f'"{c}"' for c in all_cols)
    ph_sql = ", ".join(f":{c}" for c in all_cols)
    stmt = text(
        f'INSERT INTO "DP_NOTIFY_TEMPLATE" ({col_sql}) VALUES ({ph_sql}) '
        'ON CONFLICT ("MODULE", "TEMPLATE_CODE") DO NOTHING'
    )
    params = dict(zip(_BIZ_COLS, _TEMPLATE, strict=True))
    params["CREATED_USER"] = "SYSTEM"
    params["CREATED_DATE"] = now
    params["DELETED"] = 0
    op.execute(stmt.bindparams(**params))


def downgrade() -> None:
    # 精確刪除本 migration 所種之列（比對 PK），不用寬鬆 MODULE / LIKE 範圍刪除
    op.get_bind().execute(
        text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c'),
        {"m": "DM", "c": "SUBMIT_WITHDRAWN"},
    )
