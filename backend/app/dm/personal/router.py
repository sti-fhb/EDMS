"""個人專區 API（US9 / UCDM09 / DM07）。

掛 DM 存取閘 `get_dm_context`；寫入型（刪除草稿 / 撤回）另注入 `get_operator` + service 層本人校驗 + 稽核。
個資維護（姓名 / Email / 密碼）不在本模組——由平台 DP UCDP004 提供。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.dm.deps import DmContext, get_dm_context
from app.dm.personal.schemas import ActivityResponse, DraftItem, PersonalAccess, WithdrawResult
from app.dm.personal.service import PersonalService
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER, has_role

router = APIRouter(prefix="/api/dm", tags=["dm-personal"])
_service = PersonalService()


@router.get("/personal/access", response_model=PersonalAccess)
async def personal_access(ctx: DmContext = Depends(get_dm_context)) -> PersonalAccess:
    """個人專區入口可見性（FR-004）：具編輯者或審核者角色（供前端閘側欄單項；SA 裁示 Q1=C）。"""
    return PersonalAccess(can_access=has_role(ctx.roles, DM_EDITOR) or has_role(ctx.roles, DM_REVIEWER))


@router.get("/personal/drafts", response_model=list[DraftItem])
async def list_drafts(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
) -> list[DraftItem]:
    """草稿匣（FR-001）：本人 DRAFT 版本，三類（未送審 / 被退回 / 已撤回）。"""
    return await _service.list_drafts(db, user_id=ctx.user_id)


@router.delete("/personal/drafts/{version_id}", status_code=204)
async def delete_draft(
    version_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除草稿（FR-001）：限本人 + DRAFT，軟刪、不影響已發布版本。"""
    await _service.delete_draft(db, version_id=version_id, op=op)


@router.get("/personal/activity", response_model=ActivityResponse)
async def list_activity(
    ctx: DmContext = Depends(get_dm_context),
    db: AsyncSession = Depends(get_db),
) -> ActivityResponse:
    """我的文件動態（FR-003）：近 30 天事件，依當下角色呈現撰寫者 / 審核者視角。"""
    return await _service.list_activity(db, user_id=ctx.user_id, roles=ctx.roles)


@router.post("/reviews/{review_id}/withdraw", response_model=WithdrawResult)
async def withdraw(
    review_id: int,
    ctx: DmContext = Depends(get_dm_context),
    op: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> WithdrawResult:
    """撤回送審（FR-002，撰寫者本人）：狀態回復 + 站內訊息通知原指派審核者。"""
    return await _service.withdraw(db, review_id=review_id, op=op)
