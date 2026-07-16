"""SMTP 寄送器（T020）單元測試：MIME 組裝 + MAIL_SUPPRESS_SEND 跳過（不連網）。"""

import pytest

from app.core.config import settings
from app.dp.notify.mailer import SmtpMailer, _build_mime

pytestmark = pytest.mark.unit


def test_build_mime_sets_headers_and_body():
    """_build_mime 組出 From/To/Subject/Date + 純文字內文。"""
    mime = _build_mime(recipient="a@x.com", subject="Hello", body="Body text")
    assert mime["To"] == "a@x.com"
    assert mime["Subject"] == "Hello"
    assert mime["From"] == settings.MAIL_FROM
    assert mime["Date"]  # RFC 5322 必要標頭存在
    assert mime.get_content().strip() == "Body text"


async def test_send_suppressed_skips_network(monkeypatch):
    """MAIL_SUPPRESS_SEND=true 時不呼叫 aiosmtplib（不連網、不拋錯）。"""
    monkeypatch.setattr(settings, "MAIL_SUPPRESS_SEND", True)
    called = False

    async def _fake_send(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.dp.notify.mailer.aiosmtplib.send", _fake_send)
    await SmtpMailer().send(recipient="a@x.com", subject="s", body="b")
    assert called is False
