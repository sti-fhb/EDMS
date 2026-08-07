"""DM 通知接線（T018）。

DM 事件通知一律經平台唯一發信服務 SRVDP002（`app.services.NotifyService`）送出，固定帶
`MODULE=DM` / `CALLER_MODULE=DM`。範本查找、停用略過、CHANNEL 是否寄 Email、渲染與 outbox
寫入皆由平台處理，DM 端不重造——集中化原則（研究 §7 / spec §167）。

CHANNEL 沿用平台正規詞彙（`dp/notify/schemas.py`：`Literal["EMAIL", "MSG", "BOTH"]`）：
`EMAIL` / `BOTH` 會排入 Email outbox；`MSG`（僅站內）平台回 `CHANNEL_NOT_EMAIL` 不寄信。
站內訊息之呈現於 US9 個人專區以事件動態實作，非本接線職責。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import NotifyService

_MODULE = "DM"


class DmNotifier:
    """DM 事件通知薄封裝：固定 MODULE / CALLER_MODULE 呼叫平台 SRVDP002。"""

    def __init__(self, notify: NotifyService | None = None) -> None:
        self._notify = notify or NotifyService()

    async def notify(self, db: AsyncSession, *, template_code: str, recipients: list[str], params: dict[str, str]):
        """發送一則 DM 事件通知（於呼叫方交易內 flush；呼叫方須於業務 commit 後呼叫）。

        Args:
            template_code: DM 內建範本代碼（DOC_SUBMIT / DOC_PUBLISH / AUTO_REMIND 等）。
            recipients: 收件人 Email 清單。
            params: 範本變數。

        Returns:
            平台 `SendResult`：queued_count（排入 Email PENDING 數）、skipped_reason
            （`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL` / None）。

        Raises:
            AppError: 範本不存在（404 DP_MAIL_001）、收件人超上限（422 DP_MAIL_002）。
        """
        return await self._notify.send_email(
            db,
            recipients=recipients,
            template_code=template_code,
            module=_MODULE,
            params=params,
            caller_module=_MODULE,
        )
