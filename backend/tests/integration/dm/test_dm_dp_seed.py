"""DM 範本 / 參數種子（寫入平台 DP 共用表）驗證。

驗證 DM 之 10 通知範本（MODULE=DM；US9 起含 SUBMIT_WITHDRAWN）與 DM_ 參數已種入 DP 表，且可經
SRVDP001（ParamService）讀回——確認 TBMS 前例 A（各模組 migration 種進 DP 共用表、前綴 / MODULE 隔離）落地。
"""

import pytest
from sqlalchemy import func, select

from app.dp.notify.models import DpNotifyTemplate
from app.services import ParamService

pytestmark = pytest.mark.integration


async def test_dm_templates_seeded_in_dp_table(db):
    """10 個 MODULE=DM 通知範本種入 DP_NOTIFY_TEMPLATE（US9 起含 SUBMIT_WITHDRAWN）。"""
    count = await db.scalar(select(func.count()).select_from(DpNotifyTemplate).where(DpNotifyTemplate.module == "DM"))
    assert count == 10
    codes = set(
        (await db.execute(select(DpNotifyTemplate.template_code).where(DpNotifyTemplate.module == "DM")))
        .scalars()
        .all()
    )
    assert {"DOC_SUBMIT", "DOC_PUBLISH", "KPI_WEEKLY", "UNREAD_REMIND", "AUTO_REMIND", "SUBMIT_WITHDRAWN"} <= codes


async def test_dm_template_channels(db):
    """CHANNEL 沿用平台詞彙：AUTO_REMIND=MSG（僅站內）、發布/KPI/未讀=EMAIL、送審=BOTH（Email+站內）。"""
    rows = {
        r.template_code: r
        for r in (await db.execute(select(DpNotifyTemplate).where(DpNotifyTemplate.module == "DM"))).scalars().all()
    }
    assert rows["AUTO_REMIND"].channel == "MSG"
    assert rows["SUBMIT_WITHDRAWN"].channel == "MSG"  # US9 撤回站內訊息（不寄 Email）
    assert rows["DOC_PUBLISH"].channel == "EMAIL"
    assert rows["KPI_WEEKLY"].channel == "EMAIL"
    assert rows["DOC_SUBMIT"].channel == "BOTH"
    assert all(not r.is_system for r in rows.values())  # DM 範本非系統信、可停用


async def test_dm_params_readable_via_srvdp001(db):
    """DM_ 參數經 SRVDP001（ParamService）讀回正確值（跨模組讀取路徑）。"""
    svc = ParamService()
    assert await svc.get_int_param(db, "DM_REMIND_THRESHOLD", "VALUE", 0) == 7
    assert await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", 0) == 50
    assert await svc.get_param_value(db, "DM_WEEKLY_SCHED_DAY_TIME", "VALUE") == "週一,10:00"
    assert "pdf" in (await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE") or "")
