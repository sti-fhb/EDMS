"""DM 通知接線整合測試（經平台 SRVDP002 發信，讀種子之 DM 範本）。"""

import pytest
from sqlalchemy import text

from app.dm.notify.service import DmNotifier

pytestmark = pytest.mark.integration

#: #554 的 5 支簽核流程通知與其範本佔位（key 須逐字對齊 VARIABLES，否則 _SafeFormatter
#: 會拋 KeyError → 空信 FAILED 且 queued_count=0 而不外拋，看起來就像「管道對了」）。
_FLOW_CASES = (
    ("DOC_SUBMIT", {"reviewer_name": "王", "author_name": "陳", "doc_name": "D", "review_type": "發布審核"}),
    ("DOC_REJECT", {"author_name": "陳", "doc_name": "D", "reason": "格式不符"}),
    ("OBS_SUBMIT", {"reviewer_name": "王", "applicant_name": "陳", "doc_name": "D", "reason": "已失效"}),
    ("OBS_APPROVE", {"applicant_name": "陳", "doc_name": "D"}),
    ("OBS_REJECT", {"applicant_name": "陳", "doc_name": "D", "reason": "仍需沿用"}),
)


async def test_email_channel_queues_outbox(db):
    """CHANNEL=EMAIL 之 DOC_PUBLISH → 排入 Email PENDING，記 MODULE/CALLER_MODULE=DM。

    ⚠️ 本條原本用 `DOC_SUBMIT`（當時 CHANNEL=BOTH）。#554 把 5 支簽核流程通知改為 MSG 後，
    DM 僅剩 `DOC_PUBLISH` / `KPI_WEEKLY` / `UNREAD_REMIND` 會寄 Email——**換範本而非刪測試**：
    這條驗的是「DM → 平台發信接線」本身仍可用，與哪一支範本無關；若隨著 DOC_SUBMIT 一起刪，
    接線從此沒有正向覆蓋，壞掉時只剩下方「MSG 不寄」那幾條繼續綠著。

    params key 須逐字對齊範本 VARIABLES（`doc_name,version_no,change_summary`）。
    """
    result = await DmNotifier().notify(
        db,
        template_code="DOC_PUBLISH",
        recipients=["viewer@example.com"],
        params={"doc_name": "SOP-001 作業辦法", "version_no": "1.0", "change_summary": "首版發布"},
    )
    assert result.queued_count == 1
    assert result.skipped_reason is None
    row = (
        await db.execute(
            text(
                'SELECT "MODULE", "CALLER_MODULE", "STATUS" FROM "DP_EMAIL_LOG" '
                "WHERE \"TEMPLATE_CODE\"='DOC_PUBLISH' AND \"RECIPIENT\"='viewer@example.com'"
            )
        )
    ).first()
    assert row is not None
    assert row[0] == "DM"
    assert row[1] == "DM"
    # 篩 PENDING：渲染失敗會是 FAILED，不篩就驗不出 params 是否對齊佔位
    assert row[2] == "PENDING"


async def test_flow_templates_are_msg_and_not_emailed(db):
    """#554：5 支簽核流程通知改 MSG 後，呼叫發信一律回 CHANNEL_NOT_EMAIL 且不寫 outbox。

    與下方 `test_msg_only_channel_not_emailed`（AUTO_REMIND）不同的是**母體**：那條驗的是
    「MSG 這個管道的行為」，本條驗的是「**這 5 支確實落在該管道**」。只有前者的話，5 支裡
    有人被改回 BOTH 不會有任何測試變紅。
    """
    checked = 0
    for code, params in _FLOW_CASES:
        result = await DmNotifier().notify(db, template_code=code, recipients=["x@example.com"], params=params)
        assert result.queued_count == 0, code
        assert result.skipped_reason == "CHANNEL_NOT_EMAIL", code
        checked += 1

    # ⚠️ 母體錨點必須數「迴圈實際跑了幾次」。
    # 下方 `written == 0` **不是**錨點——迴圈一條都沒跑時它一樣成立（恰是本專案一再踩到的恆真形狀）。
    assert checked == 5, f"只驗了 {checked} 支，流程通知應有 5 支"

    written = (
        await db.execute(
            text(
                'SELECT count(*) FROM "DP_EMAIL_LOG" '
                'WHERE "RECIPIENT"=\'x@example.com\' AND "TEMPLATE_CODE" IN '
                "('DOC_SUBMIT','DOC_REJECT','OBS_SUBMIT','OBS_APPROVE','OBS_REJECT')"
            )
        )
    ).scalar()
    assert written == 0


async def test_msg_only_channel_not_emailed(db):
    """CHANNEL=MSG 之 AUTO_REMIND（僅站內）→ 平台回 CHANNEL_NOT_EMAIL、不寄信。"""
    result = await DmNotifier().notify(
        db,
        template_code="AUTO_REMIND",
        recipients=["reviewer@example.com"],
        params={"reviewer_name": "王審核", "doc_name": "SOP-001", "days": "8"},
    )
    assert result.queued_count == 0
    assert result.skipped_reason == "CHANNEL_NOT_EMAIL"
