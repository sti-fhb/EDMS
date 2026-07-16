"""SMTP 寄送器（T020）。

以 aiosmtplib 直送 stdlib EmailMessage（不用 fastapi-mail 的 FastMail.send_message，
其 MIME 組裝會產生重複 Message-ID 遭部分 MTA 退信）。連線參數取自 settings；
MAIL_SUPPRESS_SEND=true 時跳過實際寄送（測試 / E2E）。
"""

import logging
from email.message import EmailMessage
from email.utils import formatdate

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_mime(*, recipient: str, subject: str, body: str) -> EmailMessage:
    """組出 stdlib EmailMessage（From/To/Subject/Date + 純文字內文）。

    主旨含非 ASCII（中文）由 stdlib 自動以 RFC 2047 編碼；Date 為 RFC 5322 必要標頭。
    """
    mime = EmailMessage()
    mime["From"] = settings.MAIL_FROM
    mime["To"] = recipient
    mime["Subject"] = subject
    mime["Date"] = formatdate()
    mime.set_content(body)
    return mime


class SmtpMailer:
    """正式 SMTP 寄送器（實作 worker 的 Mailer 介面）。"""

    async def send(self, *, recipient: str, subject: str, body: str) -> None:
        """經 SMTP 寄送單封；MAIL_SUPPRESS_SEND 開啟時跳過（不連線、不拋錯）。

        Raises:
            Exception: SMTP 連線 / 寄送失敗（由 worker 捕捉轉重試 / FAILED）。不記收件人 / 內文於例外訊息。
        """
        if settings.MAIL_SUPPRESS_SEND:
            logger.info("MAIL_SUPPRESS_SEND 開啟，跳過實際寄送")
            return
        mime = _build_mime(recipient=recipient, subject=subject, body=body)
        # use_tls（implicit TLS，埠 465）與 start_tls（STARTTLS）互斥
        await aiosmtplib.send(
            mime,
            hostname=settings.MAIL_SERVER,
            port=settings.MAIL_PORT,
            username=settings.MAIL_USERNAME or None,
            password=settings.MAIL_PASSWORD or None,
            use_tls=settings.MAIL_SSL_TLS,
            start_tls=settings.MAIL_STARTTLS and not settings.MAIL_SSL_TLS,
        )
