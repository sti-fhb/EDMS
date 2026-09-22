"""et_seed_quiz_retest_template

Revision ID: a7c31f5e9d24
Revises: f1d93a5c7b04
Create Date: 2026-09-21 15:00:00.000000

新增「測驗變更需重新測驗」通知範本（#361）。

異動說明：
- 影響 Table：`DP_NOTIFY_TEMPLATE`（`MODULE='ET'`）
- 新增 1 類範本 `QUIZ_RETEST_REQUIRED`：教師變更測驗內容並選擇「要求已通過學員重測」
  時，逐人寄送
- 沿用 #185（`et_seed_templates_params_into_dp`）之做法：參數化 INSERT +
  `ON CONFLICT DO NOTHING`、`CHANNEL='EMAIL'`、`IS_SYSTEM=false`（ET 管理者可於 DP
  後台編輯主旨／內文並啟停）

⚠️ **`VARIABLES` 必須與 `BODY` / `SUBJECT` 的佔位逐字一致**。平台的 `_SafeFormatter`
在 params key 對不上時會 KeyError → 寄出空信並記 FAILED、`queued_count=0` 且**不外拋**
——症狀是「信沒到但程式沒錯」。故此處四個變數名與 `et/notify/quiz_retest_required.py`
的 params 是同一組字面量，改任一邊都要同步。

⚠️ `CHANNEL` 只能用平台正規詞彙（`EMAIL` / `MSG` / `BOTH`，見 `dp/notify/schemas.py`
之 `Channel` Literal）——自創值會使平台 `send_email` 靜默不寄信。
"""

# ruff: noqa: S608
# S608 說明：`_seed()` 以 f-string 組出 INSERT 骨架，但代入的表名與欄位名皆為本檔內
# 之常數字面量（非外部輸入），實際「值」一律走 bindparams 參數化——無注入面。
# 比照 #185 之 et_seed_templates_params_into_dp 同一寫法與同一豁免。

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "a7c31f5e9d24"
down_revision: Union[str, None] = "f1d93a5c7b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# (MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION)
_TEMPLATES: list[tuple] = [
    (
        "ET",
        "QUIZ_RETEST_REQUIRED",
        "測驗變更需重新測驗通知",
        "【教育訓練】課程「{COURSE_NAME}」的測驗已更新，請重新測驗",
        "{USER_NAME} 您好：\n\n課程「{COURSE_NAME}」的測驗「{QUIZ_NAME}」內容已更新，"
        "教師要求已通過的學員重新測驗，您的作答次數已重新計算。\n"
        "您先前歷次的作答紀錄與成績完整保留，仍可隨時回看。\n"
        "學習連結：{COURSE_URL}" + _FOOTER,
        "USER_NAME,COURSE_NAME,QUIZ_NAME,COURSE_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
]


def _seed(table: str, biz_cols: list[str], pk_cols: list[str], rows: list[tuple], now: datetime) -> None:
    """參數化 INSERT + ON CONFLICT DO NOTHING（附標準欄位）。比照 #185 之 _seed。"""
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
    """精確刪除本 migration 所種之列（比對 PK）。

    不用寬鬆的 `MODULE='ET'` 範圍刪除——避免誤刪日後管理者於 DP 後台新增之列
    （對齊 #185 與 DM #127 之精確 downgrade 慣例）。
    """
    conn = op.get_bind()
    for module, template_code, *_ in _TEMPLATES:
        conn.execute(
            text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c').bindparams(
                m=module, c=template_code
            )
        )
