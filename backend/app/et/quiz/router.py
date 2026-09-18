"""ET 測驗設定與題目 API（US3 / #203）。

router-level 掛 `get_et_context` + `require_et_roles(ET_TEACHER, ET_ADMIN)`——本
router 服務的是 ET02 教師編輯畫面，且回應含 `OptionRow.is_correct`（正確答案）。
若只掛 `get_et_context`，等同任何登入者（人人皆有學員角色）都能把答案撈出來。

⚠️ **答案只對該課程擁有者可見（#358 第 2 項）**：`GET /quizzes/{id}` 對非擁有者把
`is_correct` 遮成 `None`，並以 `QuizDetail.answers_visible=False` 明示。理由是多重角色
可並存——兼具教師與學員者否則能先看到自己正要考的答案。寫入路徑仍為 owner-only。

⚠️ 非擁有者亦**只能讀「已發布且期間未過」的課程**（#358 M-1）：唯讀瀏覽的入口是
ET01「全部課程」清單，而它只列符合該條件者；不判的話用 id 直接打 API 就讀得到他人
草稿的題庫，違反 `spec_us3` AC 8。不符者回 404（不揭露存在）。

> 學員端的測驗作答有自己的端點與回應形狀（**不含 `is_correct`**），屬 #6。
> 兩者共用 model、但**絕不可共用 schema**。

擁有權判定在 service（回溯至所屬課程），無法以 dependency 表達。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.quiz.schemas import (
    QuestionCreateReq,
    QuestionReorderReq,
    QuestionRow,
    QuestionUpdateReq,
    QuizDetail,
    QuizUpdateReq,
)
from app.et.quiz.service import EtQuizService
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

router = APIRouter(
    prefix="/api/et",
    tags=["et-quiz"],
    dependencies=[Depends(get_et_context), Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
_service = EtQuizService()


@router.get("/quizzes/{quiz_id}", response_model=QuizDetail)
async def get_quiz(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> QuizDetail:
    """測驗詳細（設定 + 題目 + 選項 + 配分總和）。

    `points_total` 供 UI 常駐顯示「90 / 100」。總和 ≠ 100 **不在此阻擋**——教師逐題
    新增時總和必然一度不等於 100，阻擋發布是 #204 的事。
    """
    return await _service.get_detail(db, quiz_id, actor_id=ctx.user_id)


@router.put("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_quiz(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: QuizUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新測驗設定。`time_limit_min` 留空 = 不限時；`max_retry` 為 0 = 不允許重考。"""
    await _service.update_settings(db, quiz_id, req, operator=operator)


@router.post(
    "/quizzes/{quiz_id}/questions",
    response_model=QuestionRow,
    status_code=status.HTTP_201_CREATED,
)
async def add_question(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: QuestionCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> QuestionRow:
    """新增題目與其全部選項（同一請求），追加至最末。"""
    return await _service.add_question(db, quiz_id, req, operator=operator)


@router.put("/quizzes/{quiz_id}/questions/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_questions(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: QuestionReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排題目順序（教師端呈現順序；學員作答時另行洗牌）。"""
    await _service.reorder_questions(db, quiz_id, req, operator=operator)


@router.put("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_question(
    question_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: QuestionUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新題目與其選項（選項全量覆寫；帶題目自身之 `version`）。"""
    await _service.update_question(db, question_id, req, operator=operator)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除題目：本體、選項與學員作答明細皆軟刪，剩餘題目順序遞補。"""
    await _service.delete_question(db, question_id, operator=operator)
