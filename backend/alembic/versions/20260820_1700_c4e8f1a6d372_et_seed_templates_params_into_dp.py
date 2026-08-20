"""et_seed_templates_params_into_dp

Revision ID: c4e8f1a6d372
Revises: b3d7e2c9f451
Create Date: 2026-08-20 17:00:00.000000

ET 參數 / 通知範本種子寫入平台 DP 共用表（#185 T023）——依 TBMS 前例與 DM #127
（`dm_seed_templates_params_into_dp`）之既定做法：**各模組用自己的 migration 種自己
前綴 / MODULE 的列**、參數化 INSERT + `ON CONFLICT DO NOTHING`、平台不代模組種。

- `DP_PARAM_M` / `DP_PARAM_D`（前綴 `ET_`）：6 項，見 docs/specs/et/data-model.md §系統參數
- `DP_NOTIFY_TEMPLATE`（`MODULE=ET`）：7 類可維護範本，見 contracts/ext-et-email-server.md

**邊界說明**：以前綴 / `MODULE` 命名空間隔離（只碰自己的列），非破壞模組邊界——
沿用 DM #127 已確立之做法。維護 UI 於平台 DP 後台（按模組過濾）。

`CHANNEL` 一律 `EMAIL`：ET 規格未定義站內訊息，全部走 Email。**必須使用平台正規詞彙**
（`EMAIL` / `MSG` / `BOTH`，見 dp/notify/schemas.py 之 `Channel` Literal）——自創值會
使平台 `send_email` 靜默不寄信。

`IS_SYSTEM=false`：7 類皆為 ET 管理者可於 DP 後台編輯主旨 / 內文並啟停之範本；
密碼重設 / 帳號變更驗證為平台系統信（`MODULE=DP`），不在此清單、ET 不維護。

> ⚠️ **格式不一致（待 SA 定奪，不擋本次交付）**：`ET_WEEKLY_STAT_DAY_TIME` 依 ET
> data-model 取值 `MON 10:00`，而 DM 之對應參數 `DM_WEEKLY_SCHED_DAY_TIME` 用
> `週一,10:00`。兩模組排程時間格式不同，未來若由平台統一解析需先對齊。此處先照 ET
> 規格值種入（#171 之分類表亦記為 `MON 10:00`）。
"""

# ruff: noqa: S608
# S608 說明：`_seed()` 以 f-string 組出 INSERT 骨架，但**代入的表名與欄位名皆為本檔內
# 之常數字面量**（非外部輸入），實際「值」一律走 bindparams 參數化——無注入面。
# 比照 DM #127 之 dm_seed_templates_params_into_dp 同一寫法與同一豁免。

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "c4e8f1a6d372"
down_revision: Union[str, None] = "b3d7e2c9f451"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# ── ET 參數主檔 (PARAM_ID, PARAM_NAME, PARAM_TYPE, DETAIL_LOCK, DESCRIPTION) ──
_PARAM_M: list[tuple] = [
    ("ET_VIDEO_ALLOWED_FORMATS", "教材影片允許格式", "VALUE", False, "允許上傳之影片容器格式（逗號分隔）"),
    ("ET_VIDEO_MAX_SIZE_MB", "教材影片大小上限(MB)", "VALUE", False, "單支影片檔案大小上限，預設 500"),
    ("ET_VIDEO_PLAYBACK_MAX_RATE", "影片播放倍速上限", "VALUE", False, "播放器倍速上限；只能往下限縮"),
    ("ET_INVITATION_CODE_LENGTH", "邀請碼長度", "VALUE", False, "課程邀請碼位數（純數字），預設 8"),
    ("ET_WEEKLY_STAT_DAY_TIME", "每週統計與週報執行時間", "VALUE", False, "SCHET001 執行時點"),
    ("ET_URGENT_REMIND_DAYS", "截止前加急提醒天數", "VALUE", False, "SCHET002 於訖止前 N 天寄加急提醒"),
]

# ── ET 參數明細 (PARAM_ID, PARAM_KEY, PARAM_VALUE, PARAM_NAME, SORT_ORDER, IS_ENABLED) ──
_PARAM_D: list[tuple] = [
    ("ET_VIDEO_ALLOWED_FORMATS", "VALUE", "mp4,webm", "允許之影片格式", 1, True),
    ("ET_VIDEO_MAX_SIZE_MB", "VALUE", "500", "影片大小上限", 1, True),
    ("ET_VIDEO_PLAYBACK_MAX_RATE", "VALUE", "2", "倍速上限", 1, True),
    ("ET_INVITATION_CODE_LENGTH", "VALUE", "8", "邀請碼長度", 1, True),
    ("ET_WEEKLY_STAT_DAY_TIME", "VALUE", "MON 10:00", "每週執行時間", 1, True),
    ("ET_URGENT_REMIND_DAYS", "VALUE", "3", "加急提醒天數", 1, True),
]

# ── ET 7 類可維護通知範本 ──
# (MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION)
_TEMPLATES: list[tuple] = [
    (
        "ET",
        "COURSE_INVITE",
        "課程邀請通知",
        "【教育訓練】您已被加入課程「{COURSE_NAME}」",
        "{USER_NAME} 您好：\n\n您已被加入由 {TEACHER_NAME} 開設之課程「{COURSE_NAME}」。\n"
        "閱課期間：{OPEN_START_AT} ～ {OPEN_END_AT}\n學習連結：{COURSE_URL}\n"
        "（如以邀請碼加入，代碼為 {INVITATION_CODE}）" + _FOOTER,
        "USER_NAME,COURSE_NAME,TEACHER_NAME,OPEN_START_AT,OPEN_END_AT,COURSE_URL,INVITATION_CODE",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "COURSE_INVITE_DIGEST",
        "課程邀請彙整通知",
        "【教育訓練】您已被加入 數門課程",
        "{USER_NAME} 您好：\n\n因受訓單位標籤異動，您已被加入下列課程：\n\n{COURSE_LIST}" + _FOOTER,
        "USER_NAME,COURSE_LIST",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "COURSE_UPDATE",
        "課程內容更新通知",
        "【教育訓練】課程「{COURSE_NAME}」新增章節",
        "{USER_NAME} 您好：\n\n您已加入之課程「{COURSE_NAME}」新增了章節「{NEW_CHAPTER_NAME}」，"
        "請撥空完成學習。\n學習連結：{COURSE_URL}" + _FOOTER,
        "USER_NAME,COURSE_NAME,NEW_CHAPTER_NAME,COURSE_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "WEEKLY_REMIND",
        "每週未看提醒",
        "【教育訓練】您有課程尚未開始",
        "{USER_NAME} 您好：\n\n下列課程您尚未開始學習，請留意截止時間：\n\n{COURSE_LIST}" + _FOOTER,
        "USER_NAME,COURSE_LIST",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "URGENT_REMIND",
        "截止前加急提醒",
        "【教育訓練】課程「{COURSE_NAME}」即將截止",
        "{USER_NAME} 您好：\n\n課程「{COURSE_NAME}」將於 {OPEN_END_AT} 截止，您尚未完課，"
        "請儘速完成。\n學習連結：{COURSE_URL}" + _FOOTER,
        "USER_NAME,COURSE_NAME,OPEN_END_AT,COURSE_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "WEEKLY_REPORT",
        "每週看課統計週報",
        "【教育訓練】每週看課統計週報",
        "{RECIPIENT_NAME} 您好：\n\n本週看課狀況摘要如下：\n\n{REPORT_SUMMARY}\n\n"
        "逐學員明細請由此下載（需登入）：{REPORT_CSV_URL}\n"
        "※ 明細於點擊當下即時產生，數字可能與上方摘要略有時間差。" + _FOOTER,
        "RECIPIENT_NAME,REPORT_SUMMARY,REPORT_CSV_URL",
        "EMAIL",
        True,
        False,
        1,
    ),
    (
        "ET",
        "APPROVAL_PASSED",
        "線下核可通過通知",
        "【教育訓練】課程「{COURSE_NAME}」線下考核已通過",
        "{USER_NAME} 您好：\n\n您於課程「{COURSE_NAME}」之線下考核已由 {APPROVED_BY_NAME} 核可通過。\n"
        "核可時間：{APPROVED_AT}" + _FOOTER,
        "USER_NAME,COURSE_NAME,APPROVED_BY_NAME,APPROVED_AT",
        "EMAIL",
        True,
        False,
        1,
    ),
]


def _seed(table: str, biz_cols: list[str], pk_cols: list[str], rows: list[tuple], now: datetime) -> None:
    """參數化 INSERT + ON CONFLICT DO NOTHING（附標準欄位）。比照 DM #127 之 _seed。"""
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
    now = datetime.now(timezone.utc)
    _seed(
        "DP_PARAM_M",
        ["PARAM_ID", "PARAM_NAME", "PARAM_TYPE", "DETAIL_LOCK", "DESCRIPTION"],
        ["PARAM_ID"],
        _PARAM_M,
        now,
    )
    _seed(
        "DP_PARAM_D",
        ["PARAM_ID", "PARAM_KEY", "PARAM_VALUE", "PARAM_NAME", "SORT_ORDER", "IS_ENABLED"],
        ["PARAM_ID", "PARAM_KEY"],
        _PARAM_D,
        now,
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
        now,
    )


def downgrade() -> None:
    """精確刪除本 migration 所種之列（比對 PK）。

    不用寬鬆 `MODULE='ET'` / `LIKE 'ET\\_%'` 範圍刪除——避免誤刪日後管理者於 DP 後台
    新增之列（對齊平台 `dp_seed_platform_data` 與 DM #127 之精確 downgrade 慣例）。
    """
    conn = op.get_bind()
    for module, template_code, *_ in _TEMPLATES:
        conn.execute(
            text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = :m AND "TEMPLATE_CODE" = :c'),
            {"m": module, "c": template_code},
        )
    for param_id, param_key, *_ in _PARAM_D:
        conn.execute(
            text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" = :p AND "PARAM_KEY" = :k'),
            {"p": param_id, "k": param_key},
        )
    for param_id, *_ in _PARAM_M:
        conn.execute(text('DELETE FROM "DP_PARAM_M" WHERE "PARAM_ID" = :p'), {"p": param_id})
