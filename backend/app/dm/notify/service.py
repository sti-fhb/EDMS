"""DM 通知接線（T018）。

DM 事件通知一律經平台唯一發信服務 SRVDP002（`app.services.NotifyService`）送出，固定帶
`MODULE=DM` / `CALLER_MODULE=DM`。範本查找、停用略過、CHANNEL 是否寄 Email、渲染與 outbox
寫入皆由平台處理，DM 端不重造——集中化原則（研究 §7 / spec §167）。

CHANNEL 沿用平台正規詞彙（`dp/notify/schemas.py`：`Literal["EMAIL", "MSG", "BOTH"]`）：
`EMAIL` / `BOTH` 會排入 Email outbox；`MSG`（僅站內）平台回 `CHANNEL_NOT_EMAIL` 不寄信。
站內訊息之呈現於 US9 個人專區以事件動態實作，非本接線職責。

## 本封裝額外做兩件事（#563）

DM 是**全專案僅有的多人清單呼叫方**（ET 11 處全部 `recipients=[一個人]`，見
`et/notify/mailer.py`）。平台對單次收件人數設有 `MAX_RECIPIENTS` 上限，超過即拋
`AppError(422, DP_MAIL_002)`，而該例外會一路冒到 router、`get_db` 隨即 **rollback 整個
交易**。於是「可見對象相符者超過 50 人」的文件核准不了：文件沒轉 PUBLISHED、版本沒切、
`DM_CHANGE_LOG` 沒寫、稽核沒寫，而審核者看到的錯誤訊息在講寄信。

**1. 分批**：收件人切成 ≤ `MAX_RECIPIENTS` 一批逐批送出，`queued_count` 累加。

**2. 攔 `AppError`**：比照 `EtNotifier`（#273）。

兩者都收在**這個唯一出口**，不放在各呼叫點——理由同 `et/notify/service.py` 模組
docstring 所述：同一段防護寫很多遍、漏掉任一處都不會有測試發現。DM 目前只有
`review/center_service._notify_publish` 與 `kpi/service._send_weekly_report` 兩處傳多人
清單，但第三處出現時沒有任何東西會提醒它要分批；收在出口則自動涵蓋。

⚠️ **分批之後 `DP_MAIL_002` 已不可能發生**（每批恆 ≤ 上限）。下方的 `except AppError`
實際擋的只剩「範本不存在」（404 `DP_MAIL_001`）——別把它讀成還在擋收件人上限。

⚠️ **單靠攔 `AppError` 不夠，一定要有分批。** 只攔不分批等於把「硬失敗」換成「通知靜默
全失」：DOC_PUBLISH 通知可見對象是 spec FR-008 的要求，不是可有可無的附加品——新版 SOP
發布而沒人收到通知，對文件管制系統同樣是故障，只是不會有人回報。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.services import MAX_RECIPIENTS, NotifyService, SendResult

logger = logging.getLogger(__name__)

_MODULE = "DM"

#: 代表**缺陷**的 `skipped_reason`（#534）——會出 WARNING。
#: 與之相對的 `TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL` 是管理者有意的設定，不算故障。
_FAILURE_REASONS = frozenset({"RENDER_FAILED", "SEND_FAILED"})


class DmNotifier:
    """DM 事件通知薄封裝：固定 MODULE / CALLER_MODULE 呼叫平台 SRVDP002，並負責分批。"""

    def __init__(self, notify: NotifyService | None = None) -> None:
        self._notify = notify or NotifyService()

    async def notify(
        self, db: AsyncSession, *, template_code: str, recipients: list[str], params: dict[str, str]
    ) -> SendResult:
        """發送一則 DM 事件通知（於呼叫方交易內 flush；呼叫方須於業務 commit 後呼叫）。

        收件人超過 `MAX_RECIPIENTS` 時自動分批，呼叫方不需要知道上限的存在。

        Args:
            template_code: DM 內建範本代碼（DOC_SUBMIT / DOC_PUBLISH / AUTO_REMIND 等）。
            recipients: 收件人 Email 清單，長度不限。空清單不呼叫平台，直接回 `(0, None)`。
            params: 範本變數。**每一批共用同一組 params**，故逐批渲染結果相同。

        Returns:
            平台 `SendResult` 的聚合：`queued_count` 為各批之和；`skipped_reason` 取第一個
            非 None 者（`TEMPLATE_DISABLED` / `CHANNEL_NOT_EMAIL` 皆為範本層級，每批相同），
            或攔下 `AppError` 時為 `SEND_FAILED`。

        Raises:
            不拋 `AppError`。資料庫層例外**續拋**——那不是「信寄不出去」，而是這個交易本來
            就已經壞了，吞掉只會讓後續寫入在更遠的地方失敗（理由同 `EtNotifier`）。
        """
        queued = 0
        skipped_reason: str | None = None
        try:
            for start in range(0, len(recipients), MAX_RECIPIENTS):
                result = await self._notify.send_email(
                    db,
                    recipients=recipients[start : start + MAX_RECIPIENTS],
                    template_code=template_code,
                    module=_MODULE,
                    params=params,
                    caller_module=_MODULE,
                )
                queued += result.queued_count
                if skipped_reason is None:
                    skipped_reason = result.skipped_reason
        except AppError:
            # 收件人不入 log：那是個資，且此處的失敗與「寄給誰」無關（範本層級的問題）。
            # ⚠️ 回報 `queued`（已累計）而非 0——前面幾批的人**已經**寫進 outbox 了，
            # 回 0 會讓呼叫方以為一封都沒排入。
            #
            # 實務上 `queued > 0` 幾乎不會發生：此處唯一可能的 `AppError` 是範本不存在
            # （`DP_MAIL_001`），那是範本層級的條件，第 1 批就會失敗。要走到第 k>1 批才失敗，
            # 得有人在迴圈進行中把範本刪掉。別把「部分成功」讀成常態。
            #
            # ⚠️ 也因為 `DP_MAIL_001` 發生在寫入任何列之前，這條路徑是**唯一一種連
            # `DP_EMAIL_LOG` 都沒有留下痕跡**的失敗——渲染失敗至少還會寫 FAILED 列。
            logger.exception("DM 通知排入失敗，不影響呼叫方交易 template_code=%s 已排入=%s", template_code, queued)
            return SendResult(queued_count=queued, skipped_reason="SEND_FAILED")

        # #534：呼叫端只取 `queued_count`（`ApproveResult.notified` 等），`skipped_reason`
        # 到那裡就蒸發了。於是「一封都沒排入」在畫面與 API 上，與「本來就沒有收件人」長得
        # 一模一樣。本模組是 DM 全部 8 個通知呼叫點的唯一出口，在這裡留一筆即全面涵蓋。
        #
        # ⚠️ 只對**缺陷**出警告，不對「刻意跳過」出：`TEMPLATE_DISABLED` /
        # `CHANNEL_NOT_EMAIL` 是管理者的設定（DM 的 7 支站內範本每次都會回後者），
        # 一併警告會讓這行 log 在正常運作時狂噴，於是沒有人會再看它。
        if skipped_reason in _FAILURE_REASONS:
            logger.warning(
                "DM 通知未排入任何收件人 template_code=%s reason=%s 收件人數=%s",
                template_code,
                skipped_reason,
                len(recipients),
            )
        return SendResult(queued_count=queued, skipped_reason=skipped_reason)
