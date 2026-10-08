"""通知範本維護服務（US9 / dp-templates）。

DP 後台自身維護（寫入），與 SRVDP002 發信服務（service.py）分開。按 MODULE 過濾
（A-strict，比照 US5 ParamAdminService：DP 系統信共用恆見、ET / DM 需該模組管理者）；
IS_SYSTEM 系統信擋停用 / 刪除；VERSION 樂觀鎖防並行覆寫；事件固定、無新增 / 刪除；異動稽核。
特權判定依 module_admin_gate 實查（ET / DM 已於各自 bootstrap 註冊 checker）。
此前 T017 stub 過渡期一律回 False，任何人都只見得到 DP 系統信——那是「checker 未註冊」的
fail-closed 結果，非設計意圖，已隨 #250 的真授權閘一併回歸。
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
_CHANNEL_READONLY_MSG = "通知管道不可修改，如需變更請洽系統管理人員"
_MSG_ONLY_MSG = "站內通知範本不提供畫面維護"

#: DP04 僅維護**會寄 Email** 的範本（#554）。
#:
#: ⚠️ 裁示的字面是「管道為 Email」，此處實作為「會寄 Email」——`BOTH` 一併納入。今日兩者
#: 等價（#554 之後全庫無 `BOTH` 列），但日後若有人新增 `BOTH` 範本，只比對 `EMAIL` 會讓它
#: **靜默變成不可維護**：列表看不到、直呼 PUT 回 403，而沒有任何跡象說明為什麼。
#:
#: 排除的是 `MSG`：那些範本的主旨 / 內文自 #554 起沒有任何讀取端——站內呈現由各功能自己畫，
#: 中文標籤在前端 `dm/personal/schemas.ts` 映射、不讀本表。列出來只會讓人以為改了有用。
_MAINTAINABLE_CHANNELS = ("EMAIL", "BOTH")


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
        """列操作者可見且**可維護**之通知範本（DP 系統信 + 具管理者身分之模組級，且會寄 Email）。

        #554 起以 `_MAINTAINABLE_CHANNELS` 過濾——站內（`MSG`）範本不列出，因其主旨 / 內文
        已無讀取端。`update_template` 有同一道過濾，兩者必須一致，否則會留下「列表看不到、
        直呼 API 仍改得動」的路徑。
        """
        is_et, is_dm = await self._admin_flags(db, user_id)
        templates = await self._repo.list_templates(
            db, self._visible_modules(is_et, is_dm), channels=_MAINTAINABLE_CHANNELS
        )
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

        # 站內範本整列不可維護（#554）。位置有意義：
        # - 在模組過濾**之後**——否則會對無該模組權限者洩漏「這支範本是站內的」。
        # - 在下方所有欄位層檢核**之前**——整列都改不動時，個別欄位合不合法無關緊要
        #   （比照 params 的 is_editable_scope 先於值域驗證）。
        # ⚠️ 本檢核與 list_visible 的 _MAINTAINABLE_CHANNELS 是同一道，兩者必須一起改：
        #   只擋列表會留下「畫面看不到、直呼 PUT 仍改得動」的路徑。
        if template.channel not in _MAINTAINABLE_CHANNELS:
            raise AppError(status_code=403, detail=_MSG_ONLY_MSG, error_code="DP_MAIL_010")

        # CHANNEL 唯讀（#307）：管道與「實際怎麼送 / 怎麼呈現」的對應寫在程式裡、不是資料驅動的，
        # 兩個方向的改動都會靜默失效——
        #   EMAIL / BOTH → MSG：send_email 回 CHANNEL_NOT_EMAIL、queued_count=0，而畫面呈現
        #     （個人專區事件動態、簽核中心停留天數標紅）是各功能各自實作的、不會因此多出來，
        #     等於整則通知消失；
        #   MSG → EMAIL / BOTH：把為「未來站內訊息佇列」準備的內容當 Email 寄出。
        # 送出現值不算變更，前端照常送整包 payload 不受影響。解除條件：站內訊息佇列實作後。
        if data.channel != template.channel:
            raise AppError(status_code=403, detail=_CHANNEL_READONLY_MSG, error_code="DP_MAIL_009")

        # 系統信（IS_SYSTEM）保護：擋停用（is_enabled=false）。旗標驅動、不硬編碼碼清單；主旨 /
        # 內文仍可編。原本一併擋的「channel 改 MSG」已由上方通則涵蓋，故移除該分支。
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
