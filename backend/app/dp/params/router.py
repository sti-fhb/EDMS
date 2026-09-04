"""系統參數與清單維護端點（US5 / dp-params）。

授權：router-level 掛 `require_any_module_admin()`——需 ET 或 DM 任一模組管理者，
落地 spec_us5「作為 ET 或 DM 管理者」（#250，即 #61 裁示 A 註記「待 T049 回歸」之存取閘）。
寫入型注入 get_operator。**模組前綴過濾**仍於 service 依 `is_module_admin` 逐模組
enforce（A-strict，SA Q1 定案）——本閘只管「能否進後台」，不取代該模組級過濾。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.module_admin import require_any_module_admin
from app.core.operator import OperatorInfo, get_operator
from app.dp.params.schemas import ParamDetailCreate, ParamDetailResponse, ParamDetailUpdate, ParamMasterResponse
from app.dp.params.service import ParamAdminService

router = APIRouter(prefix="/api/dp/params", tags=["dp-params"], dependencies=[Depends(require_any_module_admin())])

_service = ParamAdminService()


@router.get("", response_model=list[ParamMasterResponse])
async def list_params(
    payload: JwtPayload = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
):
    """列操作者可見之參數 / 清單（平台級共用 + 具管理者身分之模組級，前綴過濾）。"""
    return await _service.list_visible(db, payload.sub)


@router.put("/{param_id}/details/{param_key}", response_model=ParamDetailResponse)
async def update_param_detail(
    param_id: str,
    param_key: str,
    data: ParamDetailUpdate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """更新明細（VALUE 改值 / LIST 改名 + 啟停）；型別 / 值域 / 越權 / 稽核由 service 把關。"""
    return await _service.update_detail(db, param_id=param_id, param_key=param_key, data=data, operator=operator)


@router.post("/{param_id}/details", response_model=ParamDetailResponse, status_code=201)
async def create_param_detail(
    param_id: str,
    data: ParamDetailCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    """新增 LIST 型清單項；DETAIL_LOCK / 型別 / 重複 / 越權 / 稽核由 service 把關。"""
    return await _service.create_detail(db, param_id=param_id, data=data, operator=operator)
