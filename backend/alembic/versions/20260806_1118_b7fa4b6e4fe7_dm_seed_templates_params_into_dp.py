"""dm_seed_templates_params_into_dp

Revision ID: b7fa4b6e4fe7
Revises: 071cc687bea9
Create Date: 2026-08-06 11:18:02.941936

DM 範本 / 參數種子寫入平台 DP 共用表（依 TBMS 前例：各模組 migration 種自己 MODULE / 前綴之列、
先驗後插 ON CONFLICT DO NOTHING、平台不代種）：
- DP_PARAM_M / DP_PARAM_D（前綴 DM_）：DM_REMIND_THRESHOLD=7 / DM_FILE_MAX_MB=50 /
  DM_FILE_TYPES / DM_WEEKLY_SCHED_DAY_TIME=週一,10:00（單值參數、PARAM_KEY=VALUE）
- DP_NOTIFY_TEMPLATE（MODULE=DM）：9 內建事件範本（DOC_SUBMIT / DOC_REJECT / DOC_PUBLISH /
  OBS_SUBMIT / OBS_APPROVE / OBS_REJECT / KPI_WEEKLY / UNREAD_REMIND / AUTO_REMIND）；
  CHANNEL：EMAIL_MSG（Email+站內）/ MSG_ONLY（僅站內，自動催辦）/ EMAIL_ONLY（僅 Email，
  發布通知 / KPI 週報 / 未讀提醒）；IS_SYSTEM=false（可停用、不可新增，事件固定）

SCHDM001 排程已由平台 DP #0 種（預留、IS_ENABLED=false，handler 待 US13 提供），此處不重種。
維護 UI 於平台 DP 後台（按模組過濾、DM 只見 DM 的列）。
"""

# ruff: noqa: S608
from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "b7fa4b6e4fe7"
down_revision: Union[str, None] = "071cc687bea9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── DM 參數主檔 (PARAM_ID, PARAM_NAME, PARAM_TYPE, DETAIL_LOCK, DESCRIPTION) ──
_PARAM_M = [
    ("DM_REMIND_THRESHOLD", "簽核催辦門檻天數", "VALUE", False, "簽核停留逾此天數自動催辦（1–30，預設 7）"),
    ("DM_FILE_MAX_MB", "檔案大小上限(MB)", "VALUE", False, "文件 / 廢止附件單檔上限，預設 50"),
    ("DM_FILE_TYPES", "可上傳檔案格式", "VALUE", False, "允許之副檔名清單（逗號分隔）"),
    (
        "DM_WEEKLY_SCHED_DAY_TIME",
        "每週排程執行時間",
        "VALUE",
        False,
        "KPI 週報 / 未讀提醒每週執行（星期,HH:MM），預設 週一,10:00",
    ),
]

# ── DM 參數明細 (PARAM_ID, PARAM_KEY, PARAM_VALUE, PARAM_NAME, SORT_ORDER, IS_ENABLED) ──
_PARAM_D = [
    ("DM_REMIND_THRESHOLD", "VALUE", "7", "催辦門檻天數", 1, True),
    ("DM_FILE_MAX_MB", "VALUE", "50", "檔案大小上限", 1, True),
    ("DM_FILE_TYPES", "VALUE", "pdf,doc,docx,xls,xlsx,ppt,pptx,jpg,jpeg,png", "可上傳格式", 1, True),
    ("DM_WEEKLY_SCHED_DAY_TIME", "VALUE", "週一,10:00", "每週執行時間", 1, True),
]

_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# ── DM 9 內建通知範本 ──
# (MODULE, TEMPLATE_CODE, TEMPLATE_NAME, SUBJECT, BODY, VARIABLES, CHANNEL, IS_ENABLED, IS_SYSTEM, VERSION)
_TEMPLATES = [
    (
        "DM",
        "DOC_SUBMIT",
        "文件送審通知",
        "【文件簽核】{doc_name} 待您審核",
        "{reviewer_name} 您好：\n\n{author_name} 送審之文件「{doc_name}」（{review_type}）待您審核，請至簽核中心處理。"
        + _FOOTER,
        "reviewer_name,author_name,doc_name,review_type",
        "EMAIL_MSG",
        True,
        False,
        1,
    ),
    (
        "DM",
        "DOC_REJECT",
        "文件退回通知",
        "【文件退回】{doc_name} 已被退回",
        "{author_name} 您好：\n\n您送審之文件「{doc_name}」已被審核者退回。退回原因：{reason}。請修改後重新送審。"
        + _FOOTER,
        "author_name,doc_name,reason",
        "EMAIL_MSG",
        True,
        False,
        1,
    ),
    (
        "DM",
        "DOC_PUBLISH",
        "文件發布通知",
        "【文件發布】{doc_name} 已發布",
        "您好：\n\n文件「{doc_name}」（版本 {version_no}）已核准發布。變更摘要：{change_summary}。" + _FOOTER,
        "doc_name,version_no,change_summary",
        "EMAIL_ONLY",
        True,
        False,
        1,
    ),
    (
        "DM",
        "OBS_SUBMIT",
        "廢止申請送審通知",
        "【廢止簽核】{doc_name} 廢止待您審核",
        "{reviewer_name} 您好：\n\n{applicant_name} 申請廢止文件「{doc_name}」待您審核。廢止原因：{reason}。" + _FOOTER,
        "reviewer_name,applicant_name,doc_name,reason",
        "EMAIL_MSG",
        True,
        False,
        1,
    ),
    (
        "DM",
        "OBS_APPROVE",
        "廢止核准通知",
        "【廢止核准】{doc_name} 已廢止",
        "{applicant_name} 您好：\n\n您申請廢止之文件「{doc_name}」已核准，該文件已下架。" + _FOOTER,
        "applicant_name,doc_name",
        "EMAIL_MSG",
        True,
        False,
        1,
    ),
    (
        "DM",
        "OBS_REJECT",
        "廢止退回通知",
        "【廢止退回】{doc_name} 廢止申請已退回",
        "{applicant_name} 您好：\n\n您申請廢止之文件「{doc_name}」已被退回，文件維持發布狀態。退回原因：{reason}。"
        + _FOOTER,
        "applicant_name,doc_name,reason",
        "EMAIL_MSG",
        True,
        False,
        1,
    ),
    (
        "DM",
        "KPI_WEEKLY",
        "閱讀 KPI 週報",
        "【KPI 週報】文件閱讀率統計",
        "管理者您好：\n\n本週文件閱讀 KPI 摘要：總文件數 {total_docs}、整體平均閱讀率 {avg_rate}。閱讀率最低前 5 份請見附件 CSV。儀表板：{dashboard_link}"
        + _FOOTER,
        "total_docs,avg_rate,dashboard_link",
        "EMAIL_ONLY",
        True,
        False,
        1,
    ),
    (
        "DM",
        "UNREAD_REMIND",
        "未讀文件提醒",
        "【未讀提醒】您有 {unread_count} 份文件尚未閱讀",
        "{viewer_name} 您好：\n\n您有 {unread_count} 份已發布文件尚未閱讀，清單如下：\n{unread_list}\n請撥空閱讀。"
        + _FOOTER,
        "viewer_name,unread_count,unread_list",
        "EMAIL_ONLY",
        True,
        False,
        1,
    ),
    (
        "DM",
        "AUTO_REMIND",
        "簽核自動催辦",
        "【催辦】{doc_name} 待簽核已逾 {days} 天",
        "{reviewer_name} 您好：\n\n文件「{doc_name}」送審已停留 {days} 天，請儘速至簽核中心處理。" + _FOOTER,
        "reviewer_name,doc_name,days",
        "MSG_ONLY",
        True,
        False,
        1,
    ),
]


def _seed(table: str, biz_cols: list[str], pk_cols: list[str], rows: list[tuple], now: datetime) -> None:
    """參數化 INSERT + ON CONFLICT DO NOTHING（附標準欄位）。"""
    all_cols = [*biz_cols, "CREATED_USER", "CREATED_DATE", "DELETED"]
    col_sql = ", ".join(f'"{c}"' for c in all_cols)
    ph_sql = ", ".join(f":{c}" for c in all_cols)
    conflict_sql = ", ".join(f'"{c}"' for c in pk_cols)
    stmt = text(f'INSERT INTO "{table}" ({col_sql}) VALUES ({ph_sql}) ON CONFLICT ({conflict_sql}) DO NOTHING')
    for row in rows:
        params = dict(zip(biz_cols, row, strict=True))
        params["CREATED_USER"] = "SYSTEM"
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
    conn = op.get_bind()
    conn.execute(text('DELETE FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = \'DM\''))
    conn.execute(text('DELETE FROM "DP_PARAM_D" WHERE "PARAM_ID" LIKE \'DM\\_%\''))
    conn.execute(text('DELETE FROM "DP_PARAM_M" WHERE "PARAM_ID" LIKE \'DM\\_%\''))
