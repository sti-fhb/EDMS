"""首頁教育訓練儀表板 API（#453 / #89 的 P3）。

## 為何掛在 `stats` 而非新開子模組

三張卡要的東西全是「聚合已有資料」，而 `stats` 已經有 `rules.summarize`、
`service.course_stat`（週報與快照共用的那一支即時計算）。另開模組會讓同一組指標
出現兩個家，而那正是本模組 docstring 一再警告的分歧來源。

## router-level 只掛 `get_et_context`

比照 `enrollment/router`：ET 學員角色於帳號建立當下即自動授予，加掛
`require_et_roles(ET_STUDENT)` 不會擋掉任何人，只會讓讀者以為這裡有實質授權。

**真正的授權在資料本身**——每張卡各自依 `ctx.roles` 決定回不回，且教師卡以
`ctx.user_id` 作為 `owner_id` 過濾，沒有「看別人的課」的參數可傳。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.et.constants import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER
from app.et.deps import EtContext, get_et_context
from app.et.stats.schemas import EtDashboard
from app.et.stats.service import EtStatsService

router = APIRouter(
    prefix="/api/et",
    tags=["et-stats"],
    dependencies=[Depends(get_et_context)],
)
_service = EtStatsService()


@router.get("/dashboard", response_model=EtDashboard)
async def dashboard(
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> EtDashboard:
    """首頁三張卡；**沒有該角色的卡回 `None`**。

    ⚠️ `None` 與「有角色但沒資料」是不同的兩件事，故不可用空內容代表無角色：前者是
    「這個人不是教師」，後者是「他是教師但目前沒有要處理的課」。兩者在前端都不渲染
    （#89 的空卡規則），但日後想對後者加一句「目前沒有待辦」時才分得出來。

    ⛔ **渲染與否由前端依「有無資料」判定，不是依角色**。#89 明訂：人人具 ET 學員
    預設角色，若照 `has_role` 顯示，主管會看到一張空的「我的課程」。

    Raises:
        AppError: 403——無任何 ET 角色（由 `get_et_context` 擋下）。
    """
    return EtDashboard(
        student=await _service.student_card(db, user_id=ctx.user_id) if ROLE_STUDENT in ctx.roles else None,
        teacher=await _service.teacher_card(db, owner_id=ctx.user_id) if ROLE_TEACHER in ctx.roles else None,
        admin=await _service.admin_card(db) if ROLE_ADMIN in ctx.roles else None,
    )
