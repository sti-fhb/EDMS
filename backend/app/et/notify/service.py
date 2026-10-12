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

## ⛔ 本封裝**不分批**，`recipients` 必須 ≤ `MAX_RECIPIENTS`（#563）

ET 目前 11 處呼叫全部是 `recipients=[一個人]`（理由見 `mailer.py:9`：平台對同批 params
只渲染一次），所以撞不到平台上限。但本方法的簽章收 `list[str]`，**第一個傳多人清單進來
的人會得到靜默全失**——超過上限時平台拋 `DP_MAIL_002`，而上面那道 `except AppError`
會把它吞成 `queued_count=0`，沒有例外、沒有 outbox 列、沒有任何人收到信。

DM 的 `DmNotifier` 已就地分批（它是全專案唯一傳多人清單的呼叫方）。ET 若日後出現多人
清單的需求，**先把分批補上**，別只是把清單傳進來。
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
            平台 `SendResult`：`queued_count`（排入 PENDING 之收件人數）、`skipped_reason`。
            後者五種值——`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL`（管理者**有意**的設定）、
            `RENDER_FAILED`（**缺陷**：範本佔位與傳入 params 對不上，#534 起具名）、
            `SEND_FAILED`（本封裝攔下 `AppError` 時自填）、`None`（成功，或收件人清單為空）。
            **寄送失敗時回 `queued_count=0`**，不拋例外——見模組 docstring。
        """
        try:
            result = await self._notify.send_email(
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

        # 與 `DmNotifier` 對稱（#534）：渲染失敗在 ET 側原本是全靜默——平台整批寫 FAILED 後
        # 回 `queued_count=0` 不拋錯，而 `DP_EMAIL_LOG` 沒有任何畫面在顯示。
        # ⚠️ 只對**缺陷**出警告：`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL` 是管理者有意的設定。
        if result.skipped_reason == "RENDER_FAILED":
            logger.warning("ET 通知渲染失敗，一封都沒排入 template_code=%s 收件人數=%s", template_code, len(recipients))
        return result
