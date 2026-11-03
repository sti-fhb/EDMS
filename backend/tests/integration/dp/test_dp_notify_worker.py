"""發信 worker（T019）整合測試：輪詢 PENDING、SMTP 收送 / 重試 / 隔離（fake mailer，真實 DB）。"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.utils import utcnow
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate
from app.dp.notify.redaction import REDACTED_BODY
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


class _RecordingBodyMailer:
    """記下寄出的 body，用以證明送進 SMTP 的是原文。"""

    def __init__(self):
        self.bodies = []

    async def send(self, *, recipient, subject, body):
        self.bodies.append(body)


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


async def test_sensitive_body_redacted_only_after_sent_persisted(db):
    """敏感系統信（#50）：失敗時 DB 保留原文；寄出後 DB 中 BODY 已遮罩。

    每次狀態轉移後 expire_all 重新查 DB（二次查詢），並**先斷言 STATUS** 再看 BODY——
    只看最終 BODY 的話，「根本沒寄成功所以還沒遮」與「遮罩了」分不出來（SA 裁示要求）。
    """
    link_body = "請點擊 https://edms.example/reset?token=PLAINTEXT 重設密碼"
    db.add(
        DpEmailLog(
            module="DP",
            template_code="PWD_RESET",
            caller_module="DP",
            recipient="a@x.com",
            subject="s",
            body=link_body,
            status="PENDING",
            retry_count=0,
            created_user="SYSTEM",
            created_date=utcnow(),
        )
    )
    await db.flush()
    worker = EmailWorker()

    await worker.process_pending_once(db, mailer=_FailMailer(), max_retry=3, interval_minutes=0)
    db.expire_all()
    row = (await _logs(db))[0]
    assert row.status == "PENDING"
    assert row.body == link_body  # 未寄成功（PENDING）：原文保留供重試

    mailer = _RecordingBodyMailer()
    await worker.process_pending_once(db, mailer=mailer, max_retry=3, interval_minutes=0)
    db.expire_all()
    row = (await _logs(db))[0]
    assert row.status == "SENT"
    assert row.body == REDACTED_BODY
    assert mailer.bodies == [link_body]  # 寄出的是原文，遮罩發生在寄出之後


class _InterruptedAfterFirst:
    """第一封寄出成功，寄第二封時被中斷（模擬後端被砍、部署重啟）。"""

    def __init__(self):
        self.sent = []

    async def send(self, *, recipient, subject, body):
        if self.sent:
            raise asyncio.CancelledError
        self.sent.append(recipient)


class _HangingMailer:
    """SMTP 一直不回應。"""

    async def send(self, *, recipient, subject, body):
        await asyncio.sleep(3600)


async def test_中途被中斷時已寄出的信維持_SENT_不會重寄(db):
    """每封寄完各自 commit（#905 A2）：整批在同一交易時，中斷會讓已寄出的信 rollback 回 PENDING、下一輪重寄。"""
    await _seed_pending(db, ["a@x.com", "b@x.com"])
    await db.commit()  # 待寄信件先落地，下面的 rollback 只會撤銷 worker 的變更
    mailer = _InterruptedAfterFirst()

    with pytest.raises(asyncio.CancelledError):
        await EmailWorker().process_pending_once(db, mailer=mailer, max_retry=3, interval_minutes=0)
    await db.rollback()

    logs = {log.recipient: log for log in await _logs(db)}
    assert mailer.sent == ["a@x.com"], "前置：第一封寄出、第二封中斷"
    assert logs["a@x.com"].status == "SENT", "已寄出的信不可被 rollback 回 PENDING"
    assert logs["b@x.com"].status == "PENDING" and logs["b@x.com"].retry_count == 0, "中斷的那封照常留待下輪"


async def test_單封寄送超過時限視為失敗_交易不會一直開著(db, monkeypatch):
    """`MAIL_SEND_TIMEOUT_SEC` 為整封信的上限（aiosmtplib 自己的逾時是每個 SMTP 指令各算一次）。"""
    monkeypatch.setattr(settings, "MAIL_SEND_TIMEOUT_SEC", 0.05)
    await _seed_pending(db, ["a@x.com"])

    sent = await asyncio.wait_for(
        EmailWorker().process_pending_once(db, mailer=_HangingMailer(), max_retry=3, interval_minutes=0), timeout=10
    )

    row = (await _logs(db))[0]
    assert sent == 0
    assert row.status == "PENDING" and row.retry_count == 1, "逾時當成一次失敗，照重試規則處理"
    assert "逾時" in row.error_msg


class _CommandTimeoutMailer:
    """aiosmtplib 自己的指令逾時（`SMTPTimeoutError` 是 `TimeoutError` 的子類）。"""

    async def send(self, *, recipient, subject, body):
        raise TimeoutError("Timed out waiting for server response")


async def test_SMTP_指令自己逾時時照原訊息記_不標成整封逾時(db):
    """只有 worker 的整封時限到了才寫「寄送逾時（超過 N 秒）」；否則維運會以為是調 `MAIL_SEND_TIMEOUT_SEC` 的問題。"""
    await _seed_pending(db, ["a@x.com"])

    await EmailWorker().process_pending_once(db, mailer=_CommandTimeoutMailer(), max_retry=3, interval_minutes=0)

    row = (await _logs(db))[0]
    assert row.retry_count == 1
    assert row.error_msg == "Timed out waiting for server response"


async def test_單輪最多寄_limit_封_其餘留待下輪(db):
    """`limit` 即 DP_PARAM MAIL.RATE_PER_MIN；拿掉上限會超出郵件主機的寄信額度而被擋信。"""
    await _seed_pending(db, ["a@x.com", "b@x.com", "c@x.com"])
    mailer = _SucceedMailer()

    sent = await EmailWorker().process_pending_once(db, mailer=mailer, max_retry=3, interval_minutes=0, limit=2)

    assert sent == 2 and len(mailer.sent) == 2
    assert sorted(log.status for log in await _logs(db)) == ["PENDING", "SENT", "SENT"]


class _NulMessageMailer:
    async def send(self, *, recipient, subject, body):
        raise RuntimeError("550 rejected\x00garbage")


async def test_SMTP_錯誤訊息含_NUL_字元時清掉後照常寫回(db):
    """PostgreSQL 的 text 不收 NUL：照原樣寫入會讓 commit 失敗，這一封每輪都排第一個、卡住後面所有信
    （security review M2）。錯誤訊息的內容由 SMTP 伺服器決定。"""
    await _seed_pending(db, ["a@x.com"])

    await EmailWorker().process_pending_once(db, mailer=_NulMessageMailer(), max_retry=3, interval_minutes=0)

    row = (await _logs(db))[0]
    assert row.retry_count == 1
    assert row.error_msg == "550 rejectedgarbage"
