"""發信 worker 敏感信 body 遮罩（#50）單元測試：fake repository / mailer，不連 DB。

SA 裁示：含一次性連結的四支系統信（PWD_RESET / EMAIL_CHANGE_VERIFY，2026-11-02 起加上
ACCOUNT_VERIFY / ACCOUNT_INVITE）於轉為 SENT **之後**遮罩 BODY；PENDING 保留原文供重試；
FAILED 由 worker 保留、超過連結時效後才由 SCHDP001 遮罩（見 test_dp_notify_redaction.py）。
持久化（flush 後二次查詢）由 integration 測試驗。
"""

import pytest

from app.dp.notify.models import DpEmailLog
from app.dp.notify.redaction import REDACTED_BODY
from app.dp.notify.worker import EmailWorker

pytestmark = pytest.mark.unit

_LINK_BODY = "請點擊 https://edms.example/reset?token=PLAINTEXT 重設密碼"


class _FakeRepo:
    """一次給一封 PENDING、跳過本輪已試過的（對應 `claim_next_pending`，#905 A2）。"""

    def __init__(self, rows):
        self._rows = rows

    async def claim_next_pending(self, db, *, interval_minutes, now, exclude):
        return next((r for r in self._rows if r.status == "PENDING" and r.message_id not in exclude), None)


class _FakeDb:
    async def commit(self):
        pass


class _RecordingMailer:
    """記下每次 send 收到的 body，用以證明寄出的是原文（未提前遮罩）。"""

    def __init__(self, fail=False):
        self._fail = fail
        self.bodies = []

    async def send(self, *, recipient, subject, body):
        self.bodies.append(body)
        if self._fail:
            raise RuntimeError("smtp down")


def _row(module="DP", template_code="PWD_RESET"):
    return DpEmailLog(
        module=module,
        template_code=template_code,
        caller_module="DP",
        recipient="a@x.com",
        subject="s",
        body=_LINK_BODY,
        status="PENDING",
        retry_count=0,
        message_id=1,  # 沒進 DB 不會配號；worker 以它排除本輪已試過的信
    )


async def _run(row, mailer, max_retry=3):
    await EmailWorker(repository=_FakeRepo([row])).process_pending_once(
        _FakeDb(), mailer=mailer, max_retry=max_retry, interval_minutes=0
    )


@pytest.mark.parametrize("template_code", ["PWD_RESET", "EMAIL_CHANGE_VERIFY", "ACCOUNT_VERIFY", "ACCOUNT_INVITE"])
async def test_sensitive_mail_redacted_after_sent(template_code):
    """敏感系統信寄出成功 → SENT 且 BODY 遮罩；mailer 收到的是原文（非提前遮罩）。"""
    row, mailer = _row(template_code=template_code), _RecordingMailer()
    await _run(row, mailer)
    assert mailer.bodies == [_LINK_BODY]
    assert row.status == "SENT"
    assert row.body == REDACTED_BODY


async def test_sensitive_mail_kept_while_pending_retry():
    """寄送失敗未達上限 → 仍 PENDING，BODY 保留原文供下輪重試。"""
    row = _row()
    await _run(row, _RecordingMailer(fail=True), max_retry=3)
    assert row.status == "PENDING"
    assert row.body == _LINK_BODY


async def test_sensitive_mail_kept_when_failed():
    """寄送失敗達上限 → FAILED，worker 不遮罩（逾連結時效才由 SCHDP001 遮）。"""
    row = _row()
    await _run(row, _RecordingMailer(fail=True), max_retry=1)
    assert row.status == "FAILED"
    assert row.body == _LINK_BODY


@pytest.mark.parametrize(
    ("module", "template_code"),
    [
        ("DP", "PWD_EXPIRY_REMIND"),  # 不含一次性連結的系統信不在範圍
        ("ET", "PWD_RESET"),  # 判定以 (MODULE, TEMPLATE_CODE) 為鍵，非僅比代碼
        ("ET", "ACCOUNT_INVITE"),
    ],
)
async def test_non_sensitive_mail_kept_after_sent(module, template_code):
    """非裁示範圍的信寄出成功 → SENT，BODY 保留快照。"""
    row = _row(module=module, template_code=template_code)
    await _run(row, _RecordingMailer())
    assert row.status == "SENT"
    assert row.body == _LINK_BODY
