"""通知範本維護端點（US9 / dp-templates）。

授權：router-level 掛 `require_any_module_admin()`——需 ET 或 DM 任一模組管理者，
落地 spec_us9「作為 ET 或 DM 管理者」（#250，即暫行案 A 註記「待 T049 回歸」之閘）。
寫入型注入 get_operator。MODULE 過濾 + 系統信保護 + 樂觀鎖 + 稽核仍由 service enforce
（A-strict）——本閘只管「能否進後台」，不取代模組級過濾。
與 SRVDP002 發信服務（service.py）分開——本檔僅後台維護 CRUD-lite（無新增 / 刪除範本）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.module_admin import require_any_module_admin
from app.core.operator import OperatorInfo, get_operator
from app.dp.notify.admin_service import TemplateAdminService
from app.dp.notify.schemas import TemplateResponse, TemplateUpdate

router = APIRouter(
    prefix="/api/dp/notify/templates", tags=["dp-templates"], dependencies=[Depends(require_any_module_admin())]
)

_service = TemplateAdminService()


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
):
    """列操作者可見之通知範本（DP 系統信共用 + 具管理者身分之模組級，MODULE 過濾）。"""
    return await _service.list_visible(db, payload.sub)


@router.put("/{module}/{template_code}", response_model=TemplateResponse)
async def update_template(
    module: str,
    template_code: str,
    data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """更新範本（主旨 / 內文 / 管道 / 啟停）；越權 / 系統信保護 / 樂觀鎖 / 稽核由 service 把關。"""
    return await _service.update_template(db, module=module, template_code=template_code, data=data, operator=operator)
