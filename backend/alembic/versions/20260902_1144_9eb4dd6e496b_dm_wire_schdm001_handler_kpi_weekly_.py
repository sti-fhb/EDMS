"""dm wire schdm001 handler + kpi_weekly template (US13)

Revision ID: 9eb4dd6e496b
Revises: 377b5d256c3e
Create Date: 2026-09-02 11:44:25.653237

接上 SCHDM001（KPI 週報 + 未讀提醒）handler 並啟用、修正 KPI_WEEKLY 範本去附件。

異動說明：
- 影響 Table：DP_SCHEDULE（更新 SCHDM001）、DP_NOTIFY_TEMPLATE（更新 KPI_WEEKLY）
- SCHDM001：HANDLER_REF 由預留 placeholder 改為 app.dm.kpi.scheduler.run、CRON_EXPR 設 `0 10 * * 1`
  （對齊 DM_WEEKLY_SCHED_DAY_TIME 預設「週一,10:00」）、IS_ENABLED 啟用（US13 handler 已交付）。
  HANDLER_REF / MODULE 不可經排程編輯 API 修改（RCE 防護），故由 migration 接線（比照 SCHDM002）。
- KPI_WEEKLY：既有種子 body 述「請見附件 CSV」與 SA 裁示（2026-09-02：平台發信不支援附件、週報改
  內文摘要 + 儀表板連結）衝突，改為內文列「閱讀率最低前 5 份」+ 儀表板連結；VARIABLES 同步。
- 皆為既有列之 UPDATE（不新增列），idempotent。
"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "9eb4dd6e496b"
down_revision: Union[str, None] = "377b5d256c3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FOOTER = "\n\n— EDMS 教育訓練文件管理系統（本信件由系統自動發送，請勿直接回覆）"

# ── SCHDM001 接線值（US13）──
_SCHDM001_HANDLER = "app.dm.kpi.scheduler.run"
_SCHDM001_CRON = "0 10 * * 1"  # 週一 10:00（對齊 DM_WEEKLY_SCHED_DAY_TIME 預設）

# 預留（回滾用）：DP #0 之 SCHDM001 種子值
_SCHDM001_HANDLER_OLD = "app.dm.schedules.handlers.pending"
_SCHDM001_CRON_OLD = "0 8 * * 1"

# ── KPI_WEEKLY 範本（US13，去附件）──
_KPI_WEEKLY_BODY = (
    "管理者您好：\n\n本週文件閱讀 KPI 摘要：\n"
    "- 總文件數：{total_docs}\n"
    "- 整體平均閱讀率：{avg_rate}\n"
    "- 閱讀率最低前 5 份：\n{lowest_list}\n\n"
    "完整逐文件明細請至 KPI 儀表板匯出 CSV。儀表板：{dashboard_link}" + _FOOTER
)
_KPI_WEEKLY_VARS = "total_docs,avg_rate,lowest_list,dashboard_link"

# 回滾用：b7fa4b6e4fe7 之 KPI_WEEKLY 種子值
_KPI_WEEKLY_BODY_OLD = (
    "管理者您好：\n\n本週文件閱讀 KPI 摘要：總文件數 {total_docs}、整體平均閱讀率 {avg_rate}。"
    "閱讀率最低前 5 份請見附件 CSV。儀表板：{dashboard_link}" + _FOOTER
)
_KPI_WEEKLY_VARS_OLD = "total_docs,avg_rate,dashboard_link"


def _update_schedule(handler: str, cron: str, enabled: bool) -> None:
    op.execute(
        text(
            'UPDATE "DP_SCHEDULE" SET "HANDLER_REF" = :h, "CRON_EXPR" = :c, "IS_ENABLED" = :e '
            "WHERE \"JOB_ID\" = 'SCHDM001'"
        ).bindparams(h=handler, c=cron, e=enabled)
    )


def _update_kpi_weekly(body: str, variables: str) -> None:
    op.execute(
        text(
            'UPDATE "DP_NOTIFY_TEMPLATE" SET "BODY" = :b, "VARIABLES" = :v '
            "WHERE \"MODULE\" = 'DM' AND \"TEMPLATE_CODE\" = 'KPI_WEEKLY'"
        ).bindparams(b=body, v=variables)
    )


def upgrade() -> None:
    _update_schedule(_SCHDM001_HANDLER, _SCHDM001_CRON, True)
    _update_kpi_weekly(_KPI_WEEKLY_BODY, _KPI_WEEKLY_VARS)


def downgrade() -> None:
    _update_schedule(_SCHDM001_HANDLER_OLD, _SCHDM001_CRON_OLD, False)
    _update_kpi_weekly(_KPI_WEEKLY_BODY_OLD, _KPI_WEEKLY_VARS_OLD)
