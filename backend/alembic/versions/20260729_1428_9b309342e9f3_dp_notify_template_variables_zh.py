"""dp_notify_template_variables_zh

Revision ID: 9b309342e9f3
Revises: 9a7ea9fd1489
Create Date: 2026-07-29 14:28:37.792014

DP 系統信範本 VARIABLES 加中文名稱（自描述，US9 手測回饋）。

異動說明：
- 影響 Table：DP_NOTIFY_TEMPLATE（僅 MODULE=DP 5 支系統信之 VARIABLES 欄）
- VARIABLES 為「可用變數說明」顯示欄（不影響範本渲染，渲染用 SUBJECT/BODY 內 {token}）；
  加中文名稱使維護頁提示更清楚（比照 US5 DP_PARAM_D.PARAM_NAME 自描述、不前端硬編碼）
- 依 TEMPLATE_CODE 精準 UPDATE、參數化綁定；downgrade 還原為純英文 token
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b309342e9f3"
down_revision: Union[str, None] = "9a7ea9fd1489"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (TEMPLATE_CODE, 中文化 VARIABLES, 原英文 VARIABLES) —— 僅 MODULE=DP 系統信
_VARS_ZH = [
    (
        "PWD_RESET",
        "user_name（使用者姓名）, reset_link（密碼重設連結）, expiry_minutes（連結有效分鐘數）",
        "user_name, reset_link, expiry_minutes",
    ),
    (
        "ACCOUNT_VERIFY",
        "user_name（使用者姓名）, verify_link（驗證連結）, expiry_minutes（連結有效分鐘數）",
        "user_name, verify_link, expiry_minutes",
    ),
    (
        "ACCOUNT_INVITE",
        "user_name（使用者姓名）, activate_link（啟用連結）, expiry_minutes（連結有效分鐘數）",
        "user_name, activate_link, expiry_minutes",
    ),
    (
        "EMAIL_CHANGE_VERIFY",
        "user_name（使用者姓名）, verify_link（驗證連結）, expiry_minutes（連結有效分鐘數）",
        "user_name, verify_link, expiry_minutes",
    ),
    (
        "PWD_EXPIRY_REMIND",
        "user_name（使用者姓名）, expiry_date（到期日）, days_left（剩餘天數）",
        "user_name, expiry_date, days_left",
    ),
]

_SQL = text('UPDATE "DP_NOTIFY_TEMPLATE" SET "VARIABLES" = :vars WHERE "MODULE" = \'DP\' AND "TEMPLATE_CODE" = :code')


def upgrade() -> None:
    for code, zh, _en in _VARS_ZH:
        op.execute(_SQL.bindparams(vars=zh, code=code))


def downgrade() -> None:
    for code, _zh, en in _VARS_ZH:
        op.execute(_SQL.bindparams(vars=en, code=code))
