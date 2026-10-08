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
# `MAX_RECIPIENTS` 同理且更必要（#563）：它是**呼叫方必須遵守**的平台不變量——超過即
# 拋 `AppError(422, DP_MAIL_002)`，而那個例外會讓呼叫方整個交易 rollback。多人清單的
# 呼叫方得據它分批，於是每個模組都需要這個數字。在各處各寫一個 50 就是雙寫，日後平台
# 調整上限時不會有任何東西報錯——ET 的 `MAX_EMAILS_PER_REQUEST` 已經為此直接 import 過
# DP 的私有名稱。由本出口公告，三方取同一個值。
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
