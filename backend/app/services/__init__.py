"""跨頂層模組呼叫的唯一出口。

其他模組（ET / DM）一律經此匯入對方之對外服務，不直接 import 對方模組的 service /
repository / model（sti-backend-boundaries API-First 隔離）。
"""

from app.dm.integration.service import DmDocumentService
from app.dp.audit.service import AuditLogService
from app.dp.notify.schemas import RenderedMail, SendResult
from app.dp.notify.service import MAX_RECIPIENTS, NotifyService
from app.dp.params.service import ParamService
from app.dp.users.account_service import AccountQueryService

# `RenderedMail` / `SendResult` 為 `NotifyService` 之回傳型別——它們**跨越模組邊界**，
# 呼叫方要標註型別就得取得它們。由本出口一併匯出，呼叫方才不必為了一個回傳型別去
# import `app.dp.notify.schemas`（那會是繞過唯一出口直接碰 DP 內部）。
#
# `MAX_RECIPIENTS` 同理（#563）：它是**呼叫方必須遵守**的平台不變量——超過即拋
# `AppError(422, DP_MAIL_002)`，而那個例外會讓呼叫方整個交易 rollback。傳多人清單的呼叫方
# 得據它分批，所以這個值必須在執行期取得，不能只是文件上的約定。目前唯一的執行期取用者是
# `DmNotifier.notify`。
#
# ⚠️ **本匯出沒有消滅既有的雙寫**，別照字面讀成「全站取同一個值」：
#   - `app/et/invitation/rules.py` 的 `MAX_EMAILS_PER_REQUEST` 是硬寫 `50`，且**刻意不 import**
#     （見該處註解）。它與平台同值這件事，單向由
#     `tests/unit/et/test_et_invitation_rules.py` 的斷言守住。
#   - `frontend/src/et/courses/invitationSchemas.ts` 另有一個硬寫的 `50`，**無任何守門**。
# 改這裡的值，上面兩處都不會報錯。
__all__ = [
    "MAX_RECIPIENTS",
    "AccountQueryService",
    "AuditLogService",
    "DmDocumentService",
    "NotifyService",
    "ParamService",
    "RenderedMail",
    "SendResult",
]
