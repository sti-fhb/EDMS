"""跨頂層模組呼叫的唯一出口。

其他模組（ET / DM）一律經此匯入對方之對外服務，不直接 import 對方模組的 service /
repository / model（sti-backend-boundaries API-First 隔離）。
"""

from app.dm.integration.service import DmDocumentService
from app.dp.audit.service import AuditLogService
from app.dp.notify.schemas import RenderedMail, SendResult
from app.dp.notify.service import NotifyService
from app.dp.params.service import ParamService
from app.dp.users.account_service import AccountQueryService

# `RenderedMail` / `SendResult` 為 `NotifyService` 之回傳型別——它們**跨越模組邊界**，
# 呼叫方要標註型別就得取得它們。由本出口一併匯出，呼叫方才不必為了一個回傳型別去
# import `app.dp.notify.schemas`（那會是繞過唯一出口直接碰 DP 內部）。
__all__ = [
    "AccountQueryService",
    "AuditLogService",
    "DmDocumentService",
    "NotifyService",
    "ParamService",
    "RenderedMail",
    "SendResult",
]
