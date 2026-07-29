"""通知範本維護服務（US9 / dp-templates）。

DP 後台自身維護（寫入），與 SRVDP002 發信服務（service.py）分開。按 MODULE 過濾
（A-strict，比照 US5 ParamAdminService：DP 系統信共用恆見、ET / DM 需該模組管理者）；
IS_SYSTEM 系統信擋停用 / 刪除；VERSION 樂觀鎖防並行覆寫；事件固定、無新增 / 刪除；異動稽核。
特權判定依 module_admin_gate（T017 stub 過渡期一律 False → 僅見 DP 系統信，待 T049）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dp.audit.service import AuditLogService
from app.dp.notify.models import DpNotifyTemplate
from app.dp.notify.repository import NotifyRepository
from app.dp.notify.schemas import TemplateResponse, TemplateUpdate

_FUNC_NAME = "DP-TEMPLATES"
_NOT_FOUND_MSG = "通知範本不存在"
_FORBIDDEN_MSG = "無權限維護此模組之範本"
_SYSTEM_MSG = "系統信不可停用或刪除（主旨與內文可編輯）"
_CONFLICT_MSG = "內容已被他人修改，請重新載入後再儲存"


def _snapshot(t: DpNotifyTemplate) -> dict:
    """稽核前後值快照（可編輯欄位）。"""
    return {"subject": t.subject, "body": t.body, "channel": t.channel, "is_enabled": t.is_enabled}


class TemplateAdminService:
    """US9 通知範本維護服務（DP 後台自身，不經 app.services 出口）。"""

    def __init__(self, repository: NotifyRepository | None = None, audit: AuditLogService | None = None) -> None:
        self._repo = repository or NotifyRepository()
        self._audit = audit or AuditLogService()

    async def _admin_flags(self, db: AsyncSession, user_id: str) -> tuple[bool, bool]:
        """回 (是否 ET 管理者, 是否 DM 管理者)；checker 未註冊時 fail-closed False（T017）。"""
        is_et = await module_admin_gate.is_module_admin("ET", user_id, db)
        is_dm = await module_admin_gate.is_module_admin("DM", user_id, db)
        return is_et, is_dm

    def _visible_modules(self, is_et: bool, is_dm: bool) -> list[str]:
        """操作者可見之 MODULE：DP 系統信共用恆見；ET / DM 需該模組管理者身分（A-strict）。"""
        modules = ["DP"]
        if is_et:
            modules.append("ET")
        if is_dm:
            modules.append("DM")
        return modules

    async def list_visible(self, db: AsyncSession, user_id: str) -> list[TemplateResponse]:
        """列操作者可見之通知範本（DP 系統信 + 具管理者身分之模組級）。"""
        is_et, is_dm = await self._admin_flags(db, user_id)
        templates = await self._repo.list_templates(db, self._visible_modules(is_et, is_dm))
        return [TemplateResponse.model_validate(t) for t in templates]

    async def update_template(
        self, db: AsyncSession, *, module: str, template_code: str, data: TemplateUpdate, operator: OperatorInfo
    ) -> TemplateResponse:
        """更新範本（主旨 / 內文 / 管道 / 啟停）；MODULE 過濾 + 系統信保護 + 樂觀鎖 + 稽核。

        Raises:
            AppError: 範本不存在（404 DP_MAIL_001）、越權（403 DP_MAIL_005）、
                系統信停用（403 DP_MAIL_003）、版本衝突（409 DP_MAIL_004）。
        """
        template = await self._repo.get_template(db, module, template_code)
        if template is None:
            raise AppError(status_code=404, detail=_NOT_FOUND_MSG, error_code="DP_MAIL_001")

        is_et, is_dm = await self._admin_flags(db, operator.user_id)
        if module not in self._visible_modules(is_et, is_dm):
            raise AppError(status_code=403, detail=_FORBIDDEN_MSG, error_code="DP_MAIL_005")

        # 系統信（IS_SYSTEM）：擋停用（is_enabled=false）；主旨 / 內文 / 管道仍可改。旗標驅動、不硬編碼碼清單。
        if template.is_system and not data.is_enabled:
            raise AppError(status_code=403, detail=_SYSTEM_MSG, error_code="DP_MAIL_003")

        before = _snapshot(template)
        now = utcnow()
        fields = {"subject": data.subject, "body": data.body, "channel": data.channel, "is_enabled": data.is_enabled}
        new_version = await self._repo.update_template_versioned(
            db,
            module=module,
            template_code=template_code,
            version=data.version,
            fields=fields,
            operator_id=operator.user_id,
            now=now,
        )
        if new_version is None:
            raise AppError(status_code=409, detail=_CONFLICT_MSG, error_code="DP_MAIL_004")

        after = {**fields}
        await self._audit.log_action(
            db,
            module="DP",
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator.user_id,
            target_id=f"{module}.{template_code}",
            description="維護通知範本",
            before_value=before,
            after_value=after,
            source_ip=get_client_ip(),
        )
        return TemplateResponse(
            module=module,
            template_code=template_code,
            template_name=template.template_name,
            subject=data.subject,
            body=data.body,
            variables=template.variables,
            channel=data.channel,
            is_enabled=data.is_enabled,
            is_system=template.is_system,
            version=new_version,
        )
