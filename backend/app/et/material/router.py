"""ET 教材內容 API（US3 / #203）。

router-level 掛 `get_et_context`（需任一 ET 角色），各端點另掛
`require_et_roles(ET_TEACHER, ET_ADMIN)`——本 router 服務的是 ET02 教師編輯畫面。
若只掛 `get_et_context`，等同任何登入者（人人皆有學員角色）都能讀到他人**草稿**
課程的教材內容，違反 spec_us3 AC 8。學員端的教材閱讀屬 #5（ET05 章節學習），
有自己的可見性規則（課程已發布、已加入、章節已解鎖）。

擁有權判定在 service（回溯至所屬課程），無法以 dependency 表達。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.material.schemas import (
    KEYWORD_MAX_LEN,
    DmDocOption,
    MaterialDetail,
    MaterialUpdateReq,
    VideoRow,
)
from app.et.material.service import EtMaterialService
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

router = APIRouter(
    prefix="/api/et",
    tags=["et-material"],
    dependencies=[Depends(get_et_context), Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
_service = EtMaterialService()


@router.get("/dm-documents", response_model=list[DmDocOption])
async def list_dm_documents(
    keyword: Annotated[str, Query(max_length=KEYWORD_MAX_LEN)] = "",
    db: AsyncSession = Depends(get_db),
) -> list[DmDocOption]:
    """DM「訓練教材」分類之文件下拉（SRVDM002）。

    ⚠️ **本路由必須宣告在 `/materials/{material_id}` 之類的動態路由之前**——同一
    prefix 下若順序顛倒會先命中動態路由。此處置於檔案最前，且路徑段不與教材重疊。
    """
    return await _service.list_dm_documents(db, keyword=keyword)


@router.get("/materials/{material_id}", response_model=MaterialDetail)
async def get_material(
    material_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> MaterialDetail:
    """教材詳細（含影片與 DM 文件引用及其廢止狀態）。"""
    return await _service.get_detail(db, material_id, actor_id=ctx.user_id)


@router.put("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_material(
    material_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: MaterialUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新教材：名稱、說明文字，與**完整的媒材集合**（`doc_ids` / `video_ids`）。

    ## 為何不是逐筆增刪端點（2026-08-26 依實測回饋改）

    文件引用原本是「加一筆打一次 API」。那讓「取消」失去意義——刪除早就送出去了；
    也讓「至少擇一媒材」被繞過——刪到一份不剩時沒有任何檢核，教材直接變空的。

    改送最終狀態後，檢核對象是**存檔後的樣子**，且未按儲存就什麼都沒發生。
    影片上傳仍是獨立端點（檔案無法暫存在 JSON 請求裡），`video_ids` 表示**要保留的**。
    """
    await _service.update(db, material_id, req, operator=operator)


@router.post(
    "/materials/{material_id}/videos",
    response_model=VideoRow,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material_video(
    material_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    file: UploadFile = File(...),
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> VideoRow:
    """上傳教材影片（multipart，**分塊串流寫檔**）。

    單檔上限取自 `DP_PARAM.ET_VIDEO_MAX_SIZE_MB`（預設 500 MB），格式取自
    `ET_VIDEO_ALLOWED_FORMATS`。長度以 `ffprobe` 解析，**取不到不存檔**
    （`ET_MATERIAL_004`）——覆蓋率的分母缺了它，章節永遠無法解鎖。
    """
    return await _service.upload_video(db, material_id, file, operator=operator)
