"""DM 通知接線整合測試（經平台 SRVDP002 發信，讀種子之 DM 範本）。"""

import pytest
from sqlalchemy import text

from app.dm.notify.service import DmNotifier

pytestmark = pytest.mark.integration


async def test_email_channel_queues_outbox(db):
    """CHANNEL=BOTH 之 DOC_SUBMIT → 排入 Email PENDING，記 MODULE/CALLER_MODULE=DM。"""
    result = await DmNotifier().notify(
        db,
        template_code="DOC_SUBMIT",
        recipients=["reviewer@example.com"],
        params={
            "reviewer_name": "王審核",
            "author_name": "陳撰寫",
            "doc_name": "SOP-001 作業辦法",
            "review_type": "發布審核",
        },
    )
    assert result.queued_count == 1
    assert result.skipped_reason is None
    row = (
        await db.execute(
            text(
                'SELECT "MODULE", "CALLER_MODULE", "STATUS" FROM "DP_EMAIL_LOG" '
                "WHERE \"TEMPLATE_CODE\"='DOC_SUBMIT' AND \"RECIPIENT\"='reviewer@example.com'"
            )
        )
    ).first()
    assert row is not None
    assert row[0] == "DM"
    assert row[1] == "DM"
    assert row[2] == "PENDING"


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
