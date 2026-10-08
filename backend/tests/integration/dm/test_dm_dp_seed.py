"""DM 範本 / 參數種子（寫入平台 DP 共用表）驗證。

驗證 DM 之 10 通知範本（MODULE=DM；US9 起含 SUBMIT_WITHDRAWN）與 DM_ 參數已種入 DP 表，且可經
SRVDP001（ParamService）讀回——確認 TBMS 前例 A（各模組 migration 種進 DP 共用表、前綴 / MODULE 隔離）落地。
"""

import pytest
from sqlalchemy import func, select, text

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
    """CHANNEL 沿用平台詞彙。#554 起 DM 只剩三支會寄 Email，簽核流程通知一律站內。

    分界是**收件人是不是送審當事人**：
    - 當事人（審核者 / 撰寫者 / 申請人）→ MSG。他們在「我的文件動態」與「簽核中心」看得到。
    - 非當事人 → EMAIL。`DOC_PUBLISH` 的收件人含可見對象相符的**閱覽者**，而閱覽者沒有
      `DM_REVIEW` 列、動態對他們是空的，DM01 文件庫也無未讀標示——改 MSG 會整則消失。
      `KPI_WEEKLY`（管理者週報）/ `UNREAD_REMIND`（催閱）同理，是推給人看而非當事人回來看。
    """
    rows = {
        r.template_code: r
        for r in (await db.execute(select(DpNotifyTemplate).where(DpNotifyTemplate.module == "DM"))).scalars().all()
    }
    # 站內（不寄 Email）——五支流程通知於 #554 由 BOTH 改入此列
    for code in (
        "AUTO_REMIND",
        "SUBMIT_WITHDRAWN",
        "DOC_SUBMIT",
        "DOC_REJECT",
        "OBS_SUBMIT",
        "OBS_APPROVE",
        "OBS_REJECT",
    ):
        assert rows[code].channel == "MSG", code
    # 仍寄 Email
    for code in ("DOC_PUBLISH", "KPI_WEEKLY", "UNREAD_REMIND"):
        assert rows[code].channel == "EMAIL", code
    # 母體對帳：上面兩組必須窮盡 DM 的全部範本，否則新增一支而沒分類不會有人發現
    assert set(rows) == {
        "AUTO_REMIND",
        "SUBMIT_WITHDRAWN",
        "DOC_SUBMIT",
        "DOC_REJECT",
        "OBS_SUBMIT",
        "OBS_APPROVE",
        "OBS_REJECT",
        "DOC_PUBLISH",
        "KPI_WEEKLY",
        "UNREAD_REMIND",
    }
    assert all(not r.is_system for r in rows.values())  # DM 範本非系統信、可停用


async def test_dm_參數三項種入平台表(db):
    """DM 於 `DP_PARAM` 的參數清單。

    原為四項；`DM_WEEKLY_SCHED_DAY_TIME` 已於 **#332** 移除——排程的**執行時點**唯一
    事實來源是 `DP_SCHEDULE.CRON_EXPR`，留著一個沒有人讀的參數會讓管理者在 DP 後台
    改了它卻完全沒有效果、且無任何錯誤訊息（ET 側於 #325 同樣處置）。

    `DM_REMIND_THRESHOLD` 留著且仍然有效：它是**業務門檻**（簽核停留幾天）而非排程
    時點，由 SCHDM002 的 handler 於執行時自行讀取。

    ⚠️ **斷言完整清單而非逐項取值**：後者對「多出一個沒人讀的參數」毫無反應，而那正是
    本次要消滅的形狀。
    """
    rows = await db.execute(
        text('SELECT "PARAM_ID" FROM "DP_PARAM_M" WHERE "PARAM_ID" LIKE :p ORDER BY 1'), {"p": r"DM\_%"}
    )
    assert rows.scalars().all() == [
        "DM_FILE_MAX_MB",
        "DM_FILE_TYPES",
        "DM_REMIND_THRESHOLD",
    ]


async def test_dm_params_readable_via_srvdp001(db):
    """DM_ 參數經 SRVDP001（ParamService）讀回正確值（跨模組讀取路徑）。"""
    svc = ParamService()
    assert await svc.get_int_param(db, "DM_REMIND_THRESHOLD", "VALUE", 0) == 7
    assert await svc.get_int_param(db, "DM_FILE_MAX_MB", "VALUE", 0) == 50
    assert "pdf" in (await svc.get_param_value(db, "DM_FILE_TYPES", "VALUE") or "")
