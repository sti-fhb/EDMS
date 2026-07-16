"""發信 worker（T019）整合測試：輪詢 PENDING、SMTP 收送 / 重試 / 隔離（fake mailer，真實 DB）。"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.notify.worker import EmailWorker
from app.services import NotifyService

pytestmark = pytest.mark.integration


class _SucceedMailer:
    def __init__(self):
        self.sent = []

    async def send(self, *, recipient, subject, body):
        self.sent.append(recipient)


class _FailMailer:
    async def send(self, *, recipient, subject, body):
        raise RuntimeError("smtp down")


class _SelectiveMailer:
    """對指定收件人失敗，其餘成功。"""

    def __init__(self, fail_for):
        self._fail_for = fail_for
        self.sent = []

    async def send(self, *, recipient, subject, body):
        if recipient in self._fail_for:
            raise RuntimeError("recipient rejected")
        self.sent.append(recipient)


async def _seed_pending(db, recipients, code="W_T"):
    now = utcnow()
    db.add(
        DpNotifyTemplate(
            module="DP",
            template_code=code,
            template_name="w",
            subject="s",
            body="b",
            channel="EMAIL",
            is_enabled=True,
            is_system=False,
            version=1,
            created_user="admin01",
            created_date=now,
        )
    )
    await db.flush()
    await NotifyService().send_email(
        db,
        recipients=recipients,
        template_code=code,
        module="DP",
        params={},
        caller_module="DP",
    )


async def _logs(db):
    result = await db.execute(select(DpEmailLog).order_by(DpEmailLog.message_id))
    return list(result.scalars().all())


async def test_worker_sends_pending(db):
    """PENDING → mailer 成功 → SENT + sent_date；回傳成功數。"""
    await _seed_pending(db, ["a@x.com", "b@x.com"])
    mailer = _SucceedMailer()
    sent = await EmailWorker().process_pending_once(db, mailer=mailer, max_retry=3, interval_minutes=0)
    assert sent == 2
    logs = await _logs(db)
    assert all(log.status == "SENT" and log.sent_date is not None for log in logs)
    assert set(mailer.sent) == {"a@x.com", "b@x.com"}


async def test_worker_retry_then_failed(db):
    """持續失敗：未達上限留 PENDING 累計 retry；達 RETRY_MAX 標 FAILED 留錯誤訊息。"""
    await _seed_pending(db, ["a@x.com"])
    worker, mailer = EmailWorker(), _FailMailer()
    # max_retry=2：第一輪 retry_count=1 仍 PENDING，第二輪達 2 → FAILED
    await worker.process_pending_once(db, mailer=mailer, max_retry=2, interval_minutes=0)
    row = (await _logs(db))[0]
    assert row.status == "PENDING" and row.retry_count == 1
    await worker.process_pending_once(db, mailer=mailer, max_retry=2, interval_minutes=0)
    row = (await _logs(db))[0]
    assert row.status == "FAILED" and row.retry_count == 2 and row.error_msg is not None


async def test_partial_failure_isolated(db):
    """單筆失敗不影響同批其他收件人。"""
    await _seed_pending(db, ["good@x.com", "bad@x.com"])
    mailer = _SelectiveMailer(fail_for={"bad@x.com"})
    await EmailWorker().process_pending_once(db, mailer=mailer, max_retry=1, interval_minutes=0)
    logs = {log.recipient: log for log in await _logs(db)}
    assert logs["good@x.com"].status == "SENT"
    assert logs["bad@x.com"].status == "FAILED"  # max_retry=1，一次失敗即達上限


async def test_worker_respects_retry_interval(db):
    """重試間隔未到的失敗信件不重覆嘗試（依 updated_date + interval 過濾）。"""
    await _seed_pending(db, ["a@x.com"])
    worker = EmailWorker()
    now = utcnow()
    # 第一次失敗，updated_date=now，retry_count=1
    await worker.process_pending_once(db, mailer=_FailMailer(), max_retry=5, interval_minutes=5, now=now)
    # 間隔內（+2 分）再輪詢：不應被撿起（retry_count 不變）
    probe = _SucceedMailer()
    sent = await worker.process_pending_once(
        db, mailer=probe, max_retry=5, interval_minutes=5, now=now + timedelta(minutes=2)
    )
    assert sent == 0 and probe.sent == []
    row = (await _logs(db))[0]
    assert row.status == "PENDING" and row.retry_count == 1
    # 間隔已過（+6 分）：可再嘗試
    sent = await worker.process_pending_once(
        db, mailer=probe, max_retry=5, interval_minutes=5, now=now + timedelta(minutes=6)
    )
    assert sent == 1
    assert (await _logs(db))[0].status == "SENT"
