"""通知發送服務（SRVDP002）。

全 EDMS 唯一發信入口（research §8）：各模組傳 template_code + 收件人，服務渲染範本、
逐收件人寫入 outbox（DP_EMAIL_LOG，PENDING）即返回，不同步寄送、不阻塞呼叫方交易；
實際寄送由常駐 worker（見 worker.py）非同步執行。模組不自持範本、不自建佇列、不直連 SMTP。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository
from app.dp.notify.schemas import SendResult

# 系統作業建立者（DP_EMAIL_LOG 標準欄位 CREATED_USER）；實際觸發模組記於 CALLER_MODULE。
_SYSTEM_USER = "SYSTEM"


def _render(text: str, params: dict[str, str]) -> str:
    """以 params 代入範本佔位（`{var}`）；範本需要而 params 未提供的變數 → 拋 KeyError。"""
    return text.format(**params)


def _channel_allows_email(channel: str) -> bool:
    """僅 EMAIL / BOTH 寄 Email；MSG（純站內訊息、模組自理）不寄。"""
    return channel in ("EMAIL", "BOTH")


class NotifyService:
    """SRVDP002 發信服務（跨模組經 app.services 呼叫）。"""

    def __init__(self, repository: NotifyRepository | None = None) -> None:
        self._repo = repository or NotifyRepository()

    async def send_email(
        self,
        db: AsyncSession,
        *,
        recipients: list[str],
        template_code: str,
        module: str,
        params: dict[str, str],
        caller_module: str,
    ) -> SendResult:
        """渲染範本並逐收件人寫入 outbox（PENDING），即返回；不同步寄送。

        於呼叫方交易內執行（同一 db session、只 flush）；呼叫方 MUST 於業務 commit 後呼叫。

        Args:
            db: 呼叫方 AsyncSession。
            recipients: 收件人 Email 清單（逐人一列 outbox）。
            template_code: DP_NOTIFY_TEMPLATE.TEMPLATE_CODE。
            module: 範本歸屬 MODULE（DP / ET / DM）。
            params: 範本變數。
            caller_module: 呼叫方模組（記入 CALLER_MODULE）。

        Returns:
            SendResult：queued_count（排入 PENDING 的收件人數）、skipped_reason（略過原因或 None）。

        Raises:
            AppError: template_code 不存在（404 / DP_MAIL_001）。
        """
        template = await self._repo.get_template(db, module, template_code)
        if template is None:
            raise AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001")
        if not template.is_enabled:
            return SendResult(queued_count=0, skipped_reason="TEMPLATE_DISABLED")
        if not _channel_allows_email(template.channel):
            return SendResult(queued_count=0, skipped_reason="CHANNEL_NOT_EMAIL")

        # 渲染一次（同批 params 相同）；缺變數 → 整批寫 FAILED 記錄、不拋錯不阻斷呼叫方（FR-06）
        try:
            subject = _render(template.subject, params)
            body = _render(template.body, params)
        except KeyError as exc:
            error_msg = f"範本變數缺漏: {exc.args[0]}"[:500]
            await self._write_logs(db, recipients, module, template_code, caller_module, "", "", "FAILED", error_msg)
            return SendResult(queued_count=0, skipped_reason=None)

        await self._write_logs(db, recipients, module, template_code, caller_module, subject, body, "PENDING", None)
        return SendResult(queued_count=len(recipients), skipped_reason=None)

    async def _write_logs(
        self,
        db: AsyncSession,
        recipients: list[str],
        module: str,
        template_code: str,
        caller_module: str,
        subject: str,
        body: str,
        status: str,
        error_msg: str | None,
    ) -> None:
        """逐收件人寫一列 DP_EMAIL_LOG（渲染快照 + 狀態）。"""
        now = utcnow()
        for recipient in recipients:
            await self._repo.add_log(
                db,
                {
                    "module": module,
                    "template_code": template_code,
                    "caller_module": caller_module,
                    "recipient": recipient,
                    "subject": subject,
                    "body": body,
                    "status": status,
                    "error_msg": error_msg,
                    "created_user": _SYSTEM_USER,
                    "created_date": now,
                },
            )
