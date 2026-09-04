"""ET 事件通知接線（US8 / #273）。

ET 事件通知一律經平台唯一發信服務 SRVDP002（`app.services.NotifyService`）送出，固定帶
`MODULE=ET` / `CALLER_MODULE=ET`。範本查找、停用略過、CHANNEL 是否寄 Email、渲染與
outbox 寫入皆由平台處理，ET 端不重造（集中化原則）。比照 `app/dm/notify/service.py`。

CHANNEL 沿用平台正規詞彙（`dp/notify/schemas.py` 之 `Literal["EMAIL", "MSG", "BOTH"]`）；
ET 之 7 支範本皆 seed 為 `EMAIL`。**自創值會讓平台靜默不寄信**，故 ET 不新增範本、
也不在此處理 CHANNEL。

## 與 `DmNotifier` 的差異：本封裝**不讓 `AppError` 冒出去**

FR-ET-US8-03 / #273 AC 3 要求「寄送失敗 MUST NOT 影響學員之已加入狀態」。而
`NotifyService.send_email` 會對「範本不存在」（404 `DP_MAIL_001`）與「收件人超上限」
（422 `DP_MAIL_002`）拋 `AppError`——那個例外會一路冒到 router，`get_db` 隨即
**rollback 整個交易**，於是管理者刪掉一支範本，就會讓課程發布連同已寫入的
`ET_ENROLLMENT` 一起消失。

四個呼叫點（發布 / 新增標籤 / 貼標追溯 / Email 邀請）各自 try/except 是同一段防護寫
四遍、且漏掉任一處都不會有測試發現，故把它收在唯一的出口。

⚠️ **只吞 `AppError`**：資料庫層的例外（session 已失效等）必須繼續往上拋——那不是
「信寄不出去」，而是這個交易本來就已經壞了，吞掉只會讓後續寫入在更遠的地方失敗。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.services import NotifyService, SendResult

logger = logging.getLogger(__name__)

_MODULE = "ET"


class EtNotifier:
    """ET 事件通知薄封裝：固定 MODULE / CALLER_MODULE 呼叫平台 SRVDP002。"""

    def __init__(self, notify: NotifyService | None = None) -> None:
        self._notify = notify or NotifyService()

    async def notify(
        self, db: AsyncSession, *, template_code: str, recipients: list[str], params: dict[str, str]
    ) -> SendResult:
        """發送一則 ET 事件通知（於呼叫方交易內 flush，不自行 commit）。

        Args:
            template_code: ET 內建範本代碼（`COURSE_INVITE` / `COURSE_INVITE_DIGEST` 等）。
            recipients: 收件人 Email 清單。
            params: 範本變數；key 須逐字對齊範本佔位（見 `course_invite.py`）。

        Returns:
            平台 `SendResult`：`queued_count`（排入 PENDING 之收件人數）、`skipped_reason`
            （`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL` / None）。**寄送失敗時回
            `queued_count=0`**，不拋例外——見模組 docstring。
        """
        try:
            return await self._notify.send_email(
                db,
                recipients=recipients,
                template_code=template_code,
                module=_MODULE,
                params=params,
                caller_module=_MODULE,
            )
        except AppError:
            # 收件人不入 log：那是個資，且此處的失敗與「寄給誰」無關（範本層級的問題）。
            logger.exception("ET 通知排入失敗，不影響呼叫方交易 template_code=%s", template_code)
            return SendResult(queued_count=0, skipped_reason="SEND_FAILED")
