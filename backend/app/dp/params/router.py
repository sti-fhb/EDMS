"""系統參數與清單維護端點（US5 / dp-params）。

授權：router-level get_jwt_payload 認證；寫入型注入 get_operator。模組前綴過濾於
service 依 module_admin_gate.is_module_admin enforce（A-strict，SA Q1 定案）——
存取閘沿用 #61 裁示 A：不掛 require_module_admin，待 T049 回歸。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import JwtPayload, get_jwt_payload
from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.dp.params.schemas import ParamDetailCreate, ParamDetailResponse, ParamDetailUpdate, ParamMasterResponse
from app.dp.params.service import ParamAdminService

router = APIRouter(prefix="/api/dp/params", tags=["dp-params"], dependencies=[Depends(get_jwt_payload)])

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
