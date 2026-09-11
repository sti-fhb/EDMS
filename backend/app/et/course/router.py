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

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.publish_service import EtPublishService
from app.et.course.schemas import (
    MAX_BIGINT,
    Capabilities,
    ChapterCreateReq,
    ChapterItem,
    ChapterRenameReq,
    ChapterReorderReq,
    CloseCourseReq,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseStatusResult,
    CourseUpdateReq,
    ItemCreateReq,
    ItemReorderReq,
    ItemRow,
    PublishCheckResult,
    PublishResult,
    ReopenCourseReq,
    TagOption,
)
from app.et.course.service import EtCourseService
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

#: 狀態轉換與發布檢核之使用者維度上限（每分鐘）。
#:
#: 正常操作：發布一門課是 1 次 publish-check + 1 次 publish；關閉 / 再開課各 1 次。
#: 一位教師一天按不到 5 次，20 遠高於任何真實使用。
#:
#: ## 為何**不**掛在 router 層
#:
#: 本 router 同時承載課程 / 章節 / 項目的全部編輯端點。掛在 router 層會把「教師連續
#: 拖拉重排章節」也算進同一個桶——那是高頻的正常操作，會被誤擋。
#:
#: ## 為何四支端點**共用同一個分桶**
#:
#: 貴的是 `_evaluate`（`snapshot` 的 7 個彙總查詢 + 逐份 DM 文件循序查詢），而
#: `publish-check` / `publish` / `reopen` 三支都會跑它。只擋 `reopen` 的話，放大路徑
#: 換一支端點就照樣開著。`close` 一併納入是因為它與 `reopen` 構成迴圈：每次成功都寫
#: 一列 append-only 的 `DP_AUDIT_LOG`，而 `AuditLogService` 會取交易層級的
#: `pg_advisory_xact_lock`——無上限的 close ⇄ reopen 迴圈會序列化**全平台**的稽核寫入。
#:
#: ⚠️ `reopen` 的成本在**版本檢核之前**就付掉了（順序是 `ensure_reopenable` →
#: `ensure_reopen_schedule` → `_evaluate` → `mark_reopened`）。帶一個錯的 `version`
#: 連打，每一發都付完整成本、最後才回 409，永遠不會成功但成本無上界。
_STATUS_RATE_MAX: Final = 20

#: 同一 IP 每分鐘之合計上限。放寬到不會誤傷同一 NAT 出口的教師群；本維度擋的是
#: 「多開帳號線性放大」，不是管制個別使用者。比照 `survey_fill` 的 30 : 300 比例。
_STATUS_IP_RATE_MAX: Final = 200

_status_limiter = SlidingWindowRateLimiter(max_requests=_STATUS_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_status_ip_limiter = SlidingWindowRateLimiter(max_requests=_STATUS_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

_STATUS_SCOPE: Final = "et-course-status"

#: 發布檢核與狀態轉換共用之限流 dependency（四支端點掛同一組，見 `_STATUS_RATE_MAX`）。
_status_rate_limit: Final = [
    Depends(rate_limit_by_et_user(_status_limiter, _STATUS_SCOPE)),
    Depends(rate_limit_by_ip(_status_ip_limiter, _STATUS_SCOPE)),
]

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
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
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
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
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


@router.post(
    "/courses/{course_id}/close",
    response_model=CourseStatusResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def close_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: CloseCourseReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> CourseStatusResult:
    """關閉課程（US11 / #288）：立即轉「已關閉」並寫入關閉時間。

    **僅已發布課程**可關閉（409 `ET_COURSE_006`）。無過渡狀態——`PENDING_CLOSE` 已於
    2026-07-02 廢除（關閉可逆、無需終態保護）。

    ## 為何是具名動作而非 `PUT /courses/{id}` 改 `status`

    比照 `publish`：狀態轉換有各自的前提與副作用（此處寫 `CLOSED_AT`），不是一個欄位的
    賦值。若走 `PUT`，`status` 會成為可任意賦值的欄位——那條路徑能把 `CLOSED` 直接寫成
    `DRAFT`，繞過整個狀態機。
    """
    return await _publish_service.close(db, course_id, req, operator=operator)


@router.post(
    "/courses/{course_id}/reopen",
    response_model=CourseStatusResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def reopen_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: ReopenCourseReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> CourseStatusResult:
    """再開課（US11 / #288）：**強制帶一組新起訖時間**後狀態回「已發布」。

    **僅已關閉課程**可再開課（409 `ET_COURSE_007`）。學員進度接續保留、邀請碼沿用原碼
    恢復有效、`URGENT_REMIND_SENT` 歸零。

    **會重跑發布六項檢核**（#288 SA Q2 裁示 A）——關閉期間教師端仍可編輯內容，故課程
    可能已不符發布條件；不合格回 422 `ET_PUBLISH_001` + `blockers`（與 `publish` 共用
    同碼與同一份缺漏清單形狀）。
    """
    return await _publish_service.reopen(db, course_id, req, operator=operator)
