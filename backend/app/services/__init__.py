"""跨頂層模組呼叫的唯一出口。

其他模組（ET / DM）一律經此匯入對方之對外服務，不直接 import 對方模組的 service /
repository / model（sti-backend-boundaries API-First 隔離）。
"""

from app.dm.integration.service import DmDocumentService
from app.dp.audit.service import AuditLogService
from app.dp.notify.service import NotifyService
from app.dp.params.service import ParamService
from app.dp.users.account_service import AccountQueryService

__all__ = ["AccountQueryService", "AuditLogService", "DmDocumentService", "NotifyService", "ParamService"]
