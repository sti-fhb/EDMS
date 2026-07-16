"""跨頂層模組呼叫的唯一出口。

其他模組（ET / DM）一律經此匯入平台服務，不直接 import 對方模組的 service /
repository / model（sti-backend-boundaries API-First 隔離）。
"""

from app.dp.audit.service import AuditLogService
from app.dp.notify.service import NotifyService
from app.dp.params.service import ParamService

__all__ = ["AuditLogService", "NotifyService", "ParamService"]
