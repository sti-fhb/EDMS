"""dp_seed_platform_data

Revision ID: fd6f5608d0ed
Revises: 5065c9fdf7e4
Create Date: 2026-07-14 14:57:33.215456

建立平台級種子資料（參數 / 系統信範本 / 排程）。

異動說明：
- DP_PARAM_M / DP_PARAM_D：平台級參數 JWT / PWD_POLICY / LOGIN / MAIL（VALUE 組）
  與 ACTION_TYPE（LIST）；模組級 ET_ / DM_ 參數由各模組 migration 補
- DP_NOTIFY_TEMPLATE：DP 系統信 3 支（PWD_RESET / EMAIL_CHANGE_VERIFY /
  PWD_EXPIRY_REMIND，IS_SYSTEM=true）
- DP_SCHEDULE：排程 job 4 筆（SCHDP001 啟用；SCHET001 / SCHET002 / SCHDM001
  預留、IS_ENABLED=false，handler 待各模組提供）
- 全部以參數化 INSERT + ON CONFLICT DO NOTHING（idempotent，不覆蓋管理者編輯）
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "fd6f5608d0ed"
down_revision: Union[str, None] = "5065c9fdf7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PWD_RESET_BODY = (
    "{user_name} 您好：\n\n"
    "我們收到您的密碼重設申請。請點擊以下連結重設密碼：\n\n"
    "{reset_link}\n\n"
    "此連結將於 {expiry_minutes} 分鐘後失效。若非您本人操作，請忽略本信，您的密碼不會變更。\n\n"
    "— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
)
_EMAIL_CHANGE_BODY = (
    "{user_name} 您好：\n\n"
    "您申請將帳號 Email 變更為本信箱。請點擊以下連結完成驗證：\n\n"
    "{verify_link}\n\n"
    "此連結將於 {expiry_minutes} 分鐘後失效。若非您本人操作，請忽略本信。\n\n"
    "— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
)
_PWD_EXPIRY_BODY = (
    "{user_name} 您好：\n\n"
    "您的密碼將於 {expiry_date}（尚餘 {days_left} 天）到期。"
    "到期後將無法登入，請於到期前登入系統並更新密碼。\n\n"
    "— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"
)

# ── 平台級參數主檔：(PARAM_ID, PARAM_NAME, PARAM_TYPE, DETAIL_LOCK, DESCRIPTION) ──
_PARAM_M = [
    ("JWT", "JWT 設定", "VALUE", False, "JWT 存取與換發相關參數"),
    ("PWD_POLICY", "密碼政策", "VALUE", False, "密碼強度與效期政策"),
    ("LOGIN", "登入安全", "VALUE", False, "登入失敗鎖定與 Token 效期"),
    ("MAIL", "郵件設定", "VALUE", False, "寄信重試與速率"),
    ("ACTION_TYPE", "操作類別", "LIST", False, "稽核操作類別代碼清單"),
]

# ── 平台級參數明細：(PARAM_ID, PARAM_KEY, PARAM_VALUE, SORT_ORDER, IS_ENABLED) ──
_PARAM_D = [
    ("JWT", "ACCESS_TTL_MIN", "15", None, True),
    ("JWT", "RENEW_MAX_HOURS", "8", None, True),
    ("PWD_POLICY", "MIN_LEN", "8", None, True),
    ("PWD_POLICY", "ADMIN_MIN_LEN", "12", None, True),
    ("PWD_POLICY", "CHAR_TYPES", "3", None, True),
    ("PWD_POLICY", "HISTORY_COUNT", "3", None, True),
    ("PWD_POLICY", "EXPIRY_DAYS", "90", None, True),
    ("PWD_POLICY", "EXPIRY_REMIND_DAYS", "7", None, True),
    ("LOGIN", "FAIL_LOCK_COUNT", "5", None, True),
    ("LOGIN", "LOCK_MINUTES", "30", None, True),
    ("LOGIN", "RESET_TOKEN_TTL_MIN", "30", None, True),
    ("LOGIN", "EMAIL_CHANGE_TTL_MIN", "30", None, True),
    ("LOGIN", "IDLE_DISABLE_DAYS", "90", None, True),
    ("MAIL", "RETRY_MAX", "5", None, True),
    ("MAIL", "RATE_PER_MIN", "60", None, True),
    ("MAIL", "RETRY_INTERVAL_MIN", "2", None, True),
    ("ACTION_TYPE", "LOGIN", "登入", 1, True),
    ("ACTION_TYPE", "LOGOUT", "登出", 2, True),
    ("ACTION_TYPE", "CREATE", "新增", 3, True),
    ("ACTION_TYPE", "UPDATE", "修改", 4, True),
    ("ACTION_TYPE", "DELETE", "刪除", 5, True),
]

# ── DP 系統信範本：(MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION) ──
_TEMPLATES = [
    ("DP", "PWD_RESET", "密碼重設", "【EDMS】密碼重設通知", _PWD_RESET_BODY,
     "user_name, reset_link, expiry_minutes", "EMAIL", True, True, 1),
    ("DP", "EMAIL_CHANGE_VERIFY", "帳號變更驗證", "【EDMS】帳號 Email 變更驗證", _EMAIL_CHANGE_BODY,
     "user_name, verify_link, expiry_minutes", "EMAIL", True, True, 1),
    ("DP", "PWD_EXPIRY_REMIND", "密碼到期提醒", "【EDMS】密碼即將到期提醒", _PWD_EXPIRY_BODY,
     "user_name, expiry_date, days_left", "EMAIL", True, True, 1),
]

# ── 排程 job：(JOB_ID, JOB_NAME, MODULE, CRON_EXPR, HANDLER_REF, IS_ENABLED) ──
# SCHDP001 為 DP 平台自身排程（啟用）；SCHET / SCHDM 為預留列（IS_ENABLED=false，
# handler 待各模組開發時提供、cron 由模組調整）。
_SCHEDULES = [
    ("SCHDP001", "平台每日作業（閒置帳號禁用 + 密碼到期提醒）", "DP",
     "0 8 * * *", "app.dp.schedules.handlers.daily_platform_job", True),
    ("SCHET001", "ET 週報 / 提醒（預留）", "ET",
     "0 8 * * 1", "app.et.schedules.handlers.pending", False),
    ("SCHET002", "ET 到期關閉 + 加急提醒（預留）", "ET",
     "0 8 * * *", "app.et.schedules.handlers.pending", False),
    ("SCHDM001", "DM KPI 週報 + 未讀提醒（預留）", "DM",
     "0 8 * * 1", "app.dm.schedules.handlers.pending", False),
]


def _seed(table: str, biz_cols: list[str], pk_cols: list[str], rows: list[tuple], now: datetime) -> None:
    """以參數化 INSERT + ON CONFLICT DO NOTHING 寫入 seed（附標準欄位）。"""
    all_cols = [*biz_cols, "CREATED_USER", "CREATED_DATE", "DELETED"]
    col_sql = ", ".join(f'"{c}"' for c in all_cols)
    ph_sql = ", ".join(f":{c}" for c in all_cols)
    conflict_sql = ", ".join(f'"{c}"' for c in pk_cols)
    stmt = text(
        f'INSERT INTO "{table}" ({col_sql}) VALUES ({ph_sql}) '  # noqa: S608 (欄名為本檔常數，值走 bindparams)
        f"ON CONFLICT ({conflict_sql}) DO NOTHING"
    )
    for row in rows:
        params = dict(zip(biz_cols, row, strict=True))
        params["CREATED_USER"] = "SYSTEM"
        params["CREATED_DATE"] = now
        params["DELETED"] = 0
        op.execute(stmt.bindparams(**params))


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    _seed("DP_PARAM_M", ["PARAM_ID", "PARAM_NAME", "PARAM_TYPE", "DETAIL_LOCK", "DESCRIPTION"],
          ["PARAM_ID"], _PARAM_M, now)
    _seed("DP_PARAM_D", ["PARAM_ID", "PARAM_KEY", "PARAM_VALUE", "SORT_ORDER", "IS_ENABLED"],
          ["PARAM_ID", "PARAM_KEY"], _PARAM_D, now)
    _seed(
        "DP_NOTIFY_TEMPLATE",
        ["MODULE", "TEMPLATE_CODE", "TEMPLATE_NAME", "SUBJECT", "BODY", "VARIABLES",
         "CHANNEL", "IS_ENABLED", "IS_SYSTEM", "VERSION"],
        ["MODULE", "TEMPLATE_CODE"], _TEMPLATES, now,
    )
    _seed("DP_SCHEDULE", ["JOB_ID", "JOB_NAME", "MODULE", "CRON_EXPR", "HANDLER_REF", "IS_ENABLED"],
          ["JOB_ID"], _SCHEDULES, now)


def downgrade() -> None:
    # 僅刪除本 migration 種子的 PK（明確 WHERE，不清空整表）；先刪明細再刪主檔（FK）。
    # DP_PARAM_D 精確對應 upgrade 的 (PARAM_ID, PARAM_KEY) 21 對，避免誤刪日後管理者新增的 key。
    del_d = text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" = :param_id AND "PARAM_KEY" = :param_key')
    for param_id, param_key, *_ in _PARAM_D:
        op.execute(del_d.bindparams(param_id=param_id, param_key=param_key))
    op.execute(
        text('DELETE FROM "DP_PARAM_M" WHERE "PARAM_ID" IN '
             "('JWT', 'PWD_POLICY', 'LOGIN', 'MAIL', 'ACTION_TYPE')")
    )
    op.execute(
        text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = \'DP\' AND "TEMPLATE_CODE" IN '
             "('PWD_RESET', 'EMAIL_CHANGE_VERIFY', 'PWD_EXPIRY_REMIND')")
    )
    op.execute(
        text('DELETE FROM "DP_SCHEDULE" WHERE "JOB_ID" IN '
             "('SCHDP001', 'SCHET001', 'SCHET002', 'SCHDM001')")
    )
