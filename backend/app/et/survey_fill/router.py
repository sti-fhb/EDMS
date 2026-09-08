"""ET05 課後問卷填寫 API（US13 / #284）——學員端。

router-level 只掛 `get_et_context`（任一 ET 角色）。**不掛 `require_et_roles`**——
填寫者是學員，而 `survey/router.py` 那支限 `ET_TEACHER` / `ET_ADMIN`。這是兩支 router
分開的直接後果：掛錯的表現是「學員不能填」或「學員能改問卷」，兩者都不會在寫測試時
自然浮現（測試會用有權限的帳號）。

真正的授權是**在籍**，在 service 完成（`_require_facts`），無法以 dependency 表達
（要先由 `course_id` 反查成員資格）。

## 兩支端點都以 `course_id` 定址，不用 `survey_id`

一門課程 0～1 份問卷（`UX_ET_SURVEY_COURSE`），學員手上有的是課程；以 `survey_id`
定址會讓前端得先問「這門課的問卷 id 是多少」，多一趟請求換不到任何東西。

也因此**不會**出現「拿別人課程的 survey_id 來填」——授權與定址是同一個 `course_id`。

## 不掛限流

兩支端點都要「在籍 + 完課」才過得去，而送出另有 `UQ_ET_SURVEY_RESPONSE_SURVEY_USER`
擋重複——沒有可放大的成本面。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context
from app.et.survey_fill.schemas import SurveyForm, SurveySubmitReq, SurveySubmitResult
from app.et.survey_fill.service import EtSurveyFillService

router = APIRouter(
    prefix="/api/et",
    tags=["et-survey-fill"],
    dependencies=[Depends(get_et_context)],
)
_service = EtSurveyFillService()


@router.get("/courses/{course_id}/survey/form", response_model=SurveyForm)
async def survey_form(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> SurveyForm:
    """問卷題目 + 自己的作答 + 當前狀態（填寫 / 唯讀回看 / 課程已關閉）。

    `GET` 而非 `POST`：路徑上只有 `course_id`，沒有任何使用者輸入會進 query string。
    """
    return await _service.get_form(db, course_id=course_id, user_id=ctx.user_id)


@router.post(
    "/courses/{course_id}/survey/response",
    response_model=SurveySubmitResult,
    status_code=status.HTTP_201_CREATED,
)
async def submit_survey(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: SurveySubmitReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> SurveySubmitResult:
    """送出問卷填答（一人一次，送出後不可修改）。

    **沒有對應的 PUT / DELETE**（`data-model` §ET_SURVEY_RESPONSE_M：「送出後不可修改
    / 刪除」）。少寫那兩個端點就是這條規則的執行方式——寫了再用權限擋，下一個人會以為
    它只是暫時關著。同 `enrollment/router` 之「學員無退出課程端點」。
    """
    return await _service.submit(db, course_id=course_id, req=req, operator=operator)
