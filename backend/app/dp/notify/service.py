"""通知發送服務（SRVDP002）。

全 EDMS 唯一發信入口（research §8）：各模組傳 template_code + 收件人，服務渲染範本、
逐收件人寫入 outbox（DP_EMAIL_LOG，PENDING）即返回，不同步寄送、不阻塞呼叫方交易；
實際寄送由常駐 worker（見 worker.py）非同步執行。模組不自持範本、不自建佇列、不直連 SMTP。
"""

import string

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.utils import utcnow
from app.dp.notify.repository import NotifyRepository
from app.dp.notify.schemas import SendResult

# 系統作業建立者（DP_EMAIL_LOG 標準欄位 CREATED_USER）；實際觸發模組記於 CALLER_MODULE。
_SYSTEM_USER = "SYSTEM"

# 收件人單次上限（防呼叫方 bug / 濫用一次寫入海量 outbox 拖垮 worker，對齊 TBMS 慣例）
_MAX_RECIPIENTS = 50


class _SafeFormatter(string.Formatter):
    """安全範本格式器：僅允許具名佔位 `{var}`，封鎖範本注入攻擊面。

    範本（SUBJECT/BODY）由 US9 後台可編輯，等同不受信任的 format string；原生 str.format
    允許屬性 / 索引存取（`{x.__class__.__globals__...}` 可讀 JWT_SECRET_KEY）與格式規格
    （`{v:>200000000}` 可 OOM 常駐 worker）。本格式器：
    - 佔位僅接受合法識別字（拒 `{0}` / `{}` / `{a.b}` / `{a[0]}`）
    - 禁格式規格（拒 `{v:...}`）
    - 值一律 str() 後代入（即便呼叫方誤傳非 str 物件，亦無屬性存取路徑）
    """

    def get_field(self, field_name: str, args, kwargs):
        if not field_name.isidentifier():
            raise ValueError(f"範本佔位僅允許具名變數，禁屬性 / 索引 / 位置: {{{field_name}}}")
        return kwargs[field_name], field_name

    def format_field(self, value, format_spec: str) -> str:
        if format_spec:
            raise ValueError("範本佔位不得含格式規格")
        return str(value)


_formatter = _SafeFormatter()


def _render(text: str, params: dict[str, str]) -> str:
    """以 params 代入範本具名佔位（`{var}`）。

    範本需要而 params 未提供 → KeyError；範本含屬性 / 索引 / 格式規格 / 未閉合大括號 → ValueError。
    兩者由呼叫端捕捉標該批 FAILED（不外拋阻斷呼叫方）。
    """
    return _formatter.vformat(text, (), params)


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
        if len(recipients) > _MAX_RECIPIENTS:
            raise AppError(status_code=422, detail="收件人數超過單次上限", error_code="DP_MAIL_002")
        template = await self._repo.get_template(db, module, template_code)
        if template is None:
            raise AppError(status_code=404, detail="通知範本不存在", error_code="DP_MAIL_001")
        if not template.is_enabled:
            return SendResult(queued_count=0, skipped_reason="TEMPLATE_DISABLED")
        if not _channel_allows_email(template.channel):
            return SendResult(queued_count=0, skipped_reason="CHANNEL_NOT_EMAIL")

        # 渲染一次（同批 params 相同）；渲染失敗 → 整批寫 FAILED 記錄、不拋錯不阻斷呼叫方（FR-06）。
        # KeyError：範本需要的變數缺漏；ValueError/IndexError：範本含未跳脫大括號（如 HTML inline CSS）
        # 或位置佔位——一律視為渲染失敗，不得外拋讓呼叫方交易 500。
        try:
            subject = _render(template.subject, params)
            body = _render(template.body, params)
        except (KeyError, ValueError, IndexError) as exc:
            error_msg = f"範本渲染失敗: {exc}"[:500]
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
