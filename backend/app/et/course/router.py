"""ET02 課程骨架與章節編排 API（US3 / #202）。

router-level 掛 `get_et_context`（需任一 ET 角色，無則 403 `ET_AUTH_001`）。

**建立課程另掛 `require_et_roles(ET_TEACHER)`**（SA 裁示 Q2，#202）：僅具教師角色者
可建立；管理者若需建課程，於 DP 後台自行加掛教師角色即可（三角色可複選）。

編輯 / 刪除 / 章節操作之**擁有權**判定在 service（`ensure_owner`）——它需要先讀出
課程才知道擁有者，無法以 dependency 表達。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import (
    ChapterCreateReq,
    ChapterItem,
    ChapterRenameReq,
    ChapterReorderReq,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseUpdateReq,
    TagOption,
)
from app.et.course.service import EtCourseService
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.roles.authz import ET_TEACHER

router = APIRouter(prefix="/api/et", tags=["et-course"], dependencies=[Depends(get_et_context)])
_service = EtCourseService()


@router.get("/tags", response_model=list[TagOption])
async def list_tag_options(
    course_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[TagOption]:
    """受訓單位標籤下拉。

    帶 `course_id` 時另含該課程既有已掛之停用標籤——FR-ET-US3-03 規定停用標籤排除於
    可選清單但既有已掛者保留，前端需要那些資料才顯示得出已掛的 chip。
    """
    return await _service.list_tag_options(db, course_id=course_id)


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def get_course(
    course_id: int,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> CourseDetail:
    """課程詳細（含章節與標籤）。他人課程可閱覽，以 `is_owner` 表達可否編輯。"""
    return await _service.get_detail(db, course_id, actor_id=ctx.user_id)


@router.post(
    "/courses",
    response_model=CourseCreateResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_et_roles(ET_TEACHER))],
)
async def create_course(
    req: CourseCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> CourseCreateResult:
    """建立草稿課程；`OWNER_ID` 取自 JWT，不由請求帶入。"""
    return await _service.create_draft(db, req, operator=operator)


@router.put("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_course(
    course_id: int,
    req: CourseUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新基本資料與受訓單位標籤（全量覆寫，帶課程 `version` 檢核樂觀鎖）。"""
    await _service.update_basic(db, course_id, req, operator=operator)


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: int,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除草稿課程；已發布 / 已關閉者以 `ET_COURSE_006` 擋下（改用 US11 關閉）。"""
    await _service.delete_draft(db, course_id, operator=operator)


@router.post(
    "/courses/{course_id}/chapters",
    response_model=ChapterItem,
    status_code=status.HTTP_201_CREATED,
)
async def add_chapter(
    course_id: int,
    req: ChapterCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ChapterItem:
    """新增章節，追加至最末。"""
    return await _service.add_chapter(db, course_id, req, operator=operator)


@router.put("/courses/{course_id}/chapters/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_chapters(
    course_id: int,
    req: ChapterReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排章節順序（送完整順序陣列；帶**課程層** `version`）。"""
    await _service.reorder_chapters(db, course_id, req, operator=operator)


@router.put("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def rename_chapter(
    chapter_id: int,
    req: ChapterRenameReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更名章節（帶章節自身之 `version`）。"""
    await _service.rename_chapter(db, chapter_id, req, operator=operator)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(
    chapter_id: int,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除章節：本體與其下項目軟刪、學員紀錄硬刪，剩餘章節順序遞補。"""
    await _service.delete_chapter(db, chapter_id, operator=operator)
