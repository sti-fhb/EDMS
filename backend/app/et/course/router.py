"""ET02 課程骨架與章節編排 API（US3 / #202）。

router-level 掛 `get_et_context`（需任一 ET 角色，無則 403 `ET_AUTH_001`）。

**建立課程另掛 `require_et_roles(ET_TEACHER)`**（SA 裁示 Q2，#202）：僅具教師角色者
可建立；管理者若需建課程，於 DP 後台自行加掛教師角色即可（三角色可複選）。

**讀取端亦限教師 / 管理者**：本 router 服務的是 ET02 教師編輯畫面。若只掛
`get_et_context`，等同任何登入者（人人皆有學員角色）都能讀到他人的**草稿**課程，
違反 spec_us3 AC 8「儲存草稿⋯⋯學員端不顯示」。學員端的課程讀取有自己的可見性規則
（`STATUS=PUBLISHED` 且 `now >= OPEN_START_AT`），屬 ET Issue #4 / #5 之端點。

編輯 / 刪除 / 章節操作之**擁有權**判定在 service（`ensure_owner`）——它需要先讀出
課程才知道擁有者，無法以 dependency 表達。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.publish_service import EtPublishService
from app.et.course.schemas import (
    MAX_BIGINT,
    Capabilities,
    ChapterCreateReq,
    ChapterItem,
    ChapterRenameReq,
    ChapterReorderReq,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseUpdateReq,
    ItemCreateReq,
    ItemReorderReq,
    ItemRow,
    PublishCheckResult,
    PublishResult,
    TagOption,
)
from app.et.course.service import EtCourseService
from app.et.deps import EtContext, get_et_context, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

router = APIRouter(prefix="/api/et", tags=["et-course"], dependencies=[Depends(get_et_context)])
_service = EtCourseService()
_publish_service = EtPublishService()


@router.get(
    "/tags",
    response_model=list[TagOption],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def list_tag_options(
    course_id: Annotated[int | None, Query(ge=1, le=MAX_BIGINT)] = None,
    db: AsyncSession = Depends(get_db),
) -> list[TagOption]:
    """受訓單位標籤下拉。

    帶 `course_id` 時另含該課程既有已掛之停用標籤——FR-ET-US3-03 規定停用標籤排除於
    可選清單但既有已掛者保留，前端需要那些資料才顯示得出已掛的 chip。
    """
    return await _service.list_tag_options(db, course_id=course_id)


@router.get("/courses/capabilities", response_model=Capabilities)
async def get_capabilities(ctx: EtContext = Depends(get_et_context)) -> Capabilities:
    """當前使用者於課程之操作能力。

    ⚠️ **本路由必須宣告在 `/courses/{course_id}` 之前**——後者的 `course_id` 為
    `Annotated[int, Path(...)]`，若順序顛倒，`/courses/capabilities` 會先命中動態路由
    並因「capabilities 不是整數」回 422。
    """
    return _service.capabilities(ctx.roles)


@router.get(
    "/courses/{course_id}",
    response_model=CourseDetail,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def get_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
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
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: CourseUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新基本資料與受訓單位標籤（全量覆寫，帶課程 `version` 檢核樂觀鎖）。"""
    await _service.update_basic(db, course_id, req, operator=operator)


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除草稿課程；已發布 / 已關閉者以 `ET_COURSE_005` 擋下（改用 US11 關閉）。"""
    await _service.delete_draft(db, course_id, operator=operator)


@router.post(
    "/courses/{course_id}/chapters",
    response_model=ChapterItem,
    status_code=status.HTTP_201_CREATED,
)
async def add_chapter(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ChapterCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ChapterItem:
    """新增章節，追加至最末。"""
    return await _service.add_chapter(db, course_id, req, operator=operator)


@router.put("/courses/{course_id}/chapters/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_chapters(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ChapterReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排章節順序（送完整順序陣列；帶**課程層** `version`）。"""
    await _service.reorder_chapters(db, course_id, req, operator=operator)


@router.put("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def rename_chapter(
    chapter_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ChapterRenameReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更名章節（帶章節自身之 `version`）。"""
    await _service.rename_chapter(db, chapter_id, req, operator=operator)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(
    chapter_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除章節：本體、其下項目與教材 / 測驗內容、學員紀錄**皆軟刪**，剩餘章節順序遞補。"""
    await _service.delete_chapter(db, chapter_id, operator=operator)


@router.post(
    "/chapters/{chapter_id}/items",
    response_model=ItemRow,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    chapter_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ItemCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ItemRow:
    """新增章節項目（教材 / 測驗），追加至最末；同交易內建立對應之空殼內容。"""
    return await _service.add_item(db, chapter_id, req, operator=operator)


@router.put("/chapters/{chapter_id}/items/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_items(
    chapter_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ItemReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排章節內項目順序（送完整順序陣列；帶**章節層** `version`）。"""
    await _service.reorder_items(db, chapter_id, req, operator=operator)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """刪除章節項目：本體、其教材 / 測驗內容與學員紀錄皆軟刪，剩餘項目順序遞補。"""
    await _service.delete_item(db, item_id, operator=operator)


@router.get(
    "/courses/{course_id}/publish-check",
    response_model=PublishCheckResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def check_publish(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> PublishCheckResult:
    """發布**預檢**：回傳缺漏項目清單，不改變任何狀態。

    讓前端能在按下發布之前就把缺漏標示出來。這是**體驗、不是把關**——發布端點
    自身會重跑同一套檢核，繞過預檢直接打 POST 一樣擋得下來。
    """
    return await _publish_service.check(db, course_id, actor_id=ctx.user_id)


@router.post(
    "/courses/{course_id}/publish",
    response_model=PublishResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def publish_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> PublishResult:
    """發布課程：六項檢核 → 狀態轉「已發布」→ 寫入首次發布時間 → 產生 8 碼邀請碼。

    檢核未通過回 422 `ET_PUBLISH_001`，body 另帶 `blockers` 清單（AC 26 要求提示
    具體缺漏項目）。

    > 標籤自動邀請與寄通知信屬 `ET-8`（FR-ET-US3-12 後半），本端點只到狀態變更
    > 與邀請碼產生。
    """
    return await _publish_service.publish(db, course_id, operator=operator)
