"""ET02 課後問卷 API（US3 / #204）。

router-level 掛 `get_et_context` + `require_et_roles(ET_TEACHER, ET_ADMIN)`——本 router
服務的是 ET02 教師編輯畫面。

> 學員端的問卷填寫有自己的端點與回應形狀（不含 `frozen` / `responded_count` 等教師
> 端統計），屬 `ET-15`。兩者共用 model、但**不共用 schema**。

擁有權判定在 service（回溯至所屬課程），無法以 dependency 表達。

**沒有 `DELETE /surveys/{id}`**——SA 裁示（#204 Q1 → B）問卷只能停用，停用走
`PUT /surveys/{id}` 改 `is_active`。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER
from app.et.survey.schemas import (
    SurveyCreateReq,
    SurveyDetail,
    SurveyQuestionCreateReq,
    SurveyQuestionReorderReq,
    SurveyQuestionRow,
    SurveyQuestionUpdateReq,
    SurveyUpdateReq,
)
from app.et.survey.service import EtSurveyService

router = APIRouter(
    prefix="/api/et",
    tags=["et-survey"],
    dependencies=[Depends(get_et_context), Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
_service = EtSurveyService()


@router.post(
    "/courses/{course_id}/survey",
    response_model=SurveyDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_survey(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveyCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> SurveyDetail:
    """建立課後問卷（掛課程層級；課程已有 → `ET_SURVEY_002`）。"""
    return await _service.create(db, course_id, req, operator=operator)


@router.get("/courses/{course_id}/survey", response_model=SurveyDetail | None)
async def get_survey(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> SurveyDetail | None:
    """課程之問卷詳細（含題目、選項、凍結旗標與填答統計）。

    **尚未建立問卷時回 `null`、不是 404**——問卷為選配（AC 23），「沒有」是正常狀態，
    回 404 會被前端錯誤處理當成故障。
    """
    return await _service.get_by_course(db, course_id, actor_id=ctx.user_id)


@router.put("/surveys/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_survey(
    survey_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveyUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新問卷名稱與啟用狀態。

    **凍結後仍可呼叫**——AC 21 明訂已有填答時教師僅可停用問卷，停用走的正是這條。
    """
    await _service.update_basic(db, survey_id, req, operator=operator)


@router.post(
    "/surveys/{survey_id}/questions",
    response_model=SurveyQuestionRow,
    status_code=status.HTTP_201_CREATED,
)
async def add_survey_question(
    survey_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveyQuestionCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> SurveyQuestionRow:
    """新增題目與其全部選項（同一請求），追加至最末。題型固定單選。"""
    return await _service.add_question(db, survey_id, req, operator=operator)


@router.put("/surveys/{survey_id}/questions/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_survey_questions(
    survey_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveyQuestionReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排題目順序（問卷題目保留教師排序，不洗牌）。"""
    await _service.reorder_questions(db, survey_id, req, operator=operator)


@router.put("/survey-questions/{sq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_survey_question(
    sq_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveyQuestionUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新題目與其選項（選項全量覆寫；帶題目自身之 `version`）。"""
    await _service.update_question(db, sq_id, req, operator=operator)


@router.delete("/survey-questions/{sq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survey_question(
    sq_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除題目：本體與選項軟刪，剩餘題目順序遞補。"""
    await _service.delete_question(db, sq_id, operator=operator)
