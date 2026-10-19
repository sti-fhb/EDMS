"""ET05 課程骨架與章節編排 API（US3 / #202）；亦含 ET01 課程清單（US7 / #299）。

router-level 掛 `get_et_context`（需任一 ET 角色，無則 403 `ET_AUTH_001`）。

**建立課程另掛 `require_et_roles(ET_TEACHER)`**（SA 裁示 Q2，#202）：僅具教師角色者
可建立；管理者若需建課程，於 DP 後台自行加掛教師角色即可（三角色可複選）。

**讀取端亦限教師 / 管理者**：本 router 服務的是 ET05 教師編輯畫面。若只掛
`get_et_context`，等同任何登入者（人人皆有學員角色）都能讀到他人的**草稿**課程，
違反 spec_us3 AC 8「儲存草稿⋯⋯學員端不顯示」。學員端的課程讀取有自己的可見性規則
（`STATUS=PUBLISHED` 且 `now >= OPEN_START_AT`），屬 ET Issue #4 / #5 之端點。

編輯 / 刪除 / 章節操作之**擁有權**判定在 service（`ensure_owner`）——它需要先讀出
課程才知道擁有者，無法以 dependency 表達。
"""

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse
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
    ContentUpdateResult,
    CourseCard,
    CourseCreateReq,
    CourseCreateResult,
    CourseDetail,
    CourseStatusResult,
    CourseUpdateReq,
    ItemCreateReq,
    ItemReorderReq,
    ItemRow,
    OwnerOption,
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
#: 正常操作：發布一門課是 1 次 publish-check + 1 次 publish；關閉 / 再開課各 1 次；
#: 已發布課程的內容「更新」（#631）一次編輯一次。一位教師一天按不到 10 次，20 仍遠
#: 高於任何真實使用。
#:
#: ## 為何**不**掛在 router 層
#:
#: 本 router 同時承載課程 / 章節 / 項目的全部編輯端點。掛在 router 層會把「教師連續
#: 拖拉重排章節」也算進同一個桶——那是高頻的正常操作，會被誤擋。
#:
#: ## 為何五支端點**共用同一個分桶**
#:
#: 貴的是**檢核**（彙總查詢 + 逐份 DM 文件循序查詢），而 `publish-check` / `publish` /
#: `reopen` / `content/apply` 四支都會跑它（前三支走活表的 `snapshot`，`content/apply`
#: 走暫存樹，但同樣要逐份問 DM 廢止狀態）。只擋其中一支的話，放大路徑換一支端點
#: 就照樣開著。`close` 一併納入是因為它與 `reopen` 構成迴圈：每次成功都寫
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

#: 新增章節之上限（每分鐘）。**與 `_STATUS_RATE_MAX` 分桶**。
#:
#: 自 #303 起，對已發布課程新增章節會對**全班在籍學員**各寄一封 `COURSE_UPDATE`：
#: 一次 POST = N 次「查範本 + 寫 outbox」，N 等於在籍人數、無上界。掛「全體」標籤的
#: 課程發布時會把全站學員帶入，於是 N 可以是整個組織。
#:
#: 門檻取 30：「儲存並繼續新增」是連續操作（#203），教師一口氣建十幾個章節是正常的；
#: 30 容得下那種用法，但把「每秒數發」的放大關掉。
_CHAPTER_RATE_MAX: Final = 30

#: 同一 IP 每分鐘之合計上限。比照 `survey_fill` 的 1 : 10 比例放寬，避免誤傷同一 NAT
#: 出口的教師群。
_CHAPTER_IP_RATE_MAX: Final = 300

_chapter_limiter = SlidingWindowRateLimiter(max_requests=_CHAPTER_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_chapter_ip_limiter = SlidingWindowRateLimiter(max_requests=_CHAPTER_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

_CHAPTER_SCOPE: Final = "et-course-chapter"

_chapter_rate_limit: Final = [
    Depends(rate_limit_by_et_user(_chapter_limiter, _CHAPTER_SCOPE)),
    Depends(rate_limit_by_ip(_chapter_ip_limiter, _CHAPTER_SCOPE)),
]

router = APIRouter(prefix="/api/et", tags=["et-course"], dependencies=[Depends(get_et_context)])
_service = EtCourseService()
_publish_service = EtPublishService()


@router.get(
    "/courses",
    response_model=PagedResponse[CourseCard],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def list_courses(
    scope: Annotated[Literal["mine", "all"], Query()],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
    q: Annotated[str | None, Query(max_length=100)] = None,
    tag_id: Annotated[int | None, Query(ge=1, le=MAX_BIGINT)] = None,
    unit_tag_id: Annotated[int | None, Query(ge=1, le=MAX_BIGINT)] = None,
    owner_id: Annotated[str | None, Query(max_length=20)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 12,
) -> PagedResponse[CourseCard]:
    """ET01 課程清單（`FR-ET-US7-01`~`-04`）。

    | `scope` | 擁有者 | 狀態 | 在籍 |
    |---|---|---|---|
    | `mine` | 限本人 | **全部**（草稿 / 已發布 / 已關閉）——教師要管理自己的課 | 不限 |
    | `all` | 不限 | **僅已發布**——草稿的存在對他人是秘密，已關閉者不列入 | **排除呼叫者已在籍者** |

    `all` 排除已在籍的課程是**刻意的**（#521）：那門課只能從「我的課程」以學員視角進入，
    本分頁點進去因此必然是預覽。⛔ 若有人回報「我加入的課在全部課程不見了」，那不是
    bug——不要為了把它加回來而引進預覽旗標，理由見 `repository.build_list_stmt`。

    `q` 依課程名稱模糊比對（萬用字元已跳脫）；`tag_id`（職位）/ `unit_tag_id`（單位）比對課程配對的
    **字面值**、不展開通用值，兩者並用時須同一組配對同時符合（#538 SA Q2）；
    `owner_id` 僅於 `scope=all` 有意義，`scope=mine` 時**忽略而不報錯**——那是前端切分頁
    時沒清乾淨，不是使用者做錯事。

    `limit` 預設 12：卡片網格在桌機是每列三張，12 剛好四列。
    """
    return await _service.list_courses(
        db,
        actor_id=ctx.user_id,
        scope=scope,
        keyword=q,
        tag_id=tag_id,
        unit_tag_id=unit_tag_id,
        owner_id=owner_id,
        page=page,
        limit=limit,
    )


@router.get(
    "/courses/filter-tags",
    response_model=list[TagOption],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def list_filter_tags(db: AsyncSession = Depends(get_db)) -> list[TagOption]:
    """ET01 篩選用的標籤下拉：**`ET_TAG` 全部，含停用者**。

    ⚠️ 與 `GET /tags` **語意相反、不可互換**：那支是 ET05 編輯時掛標籤用的（停用者不得
    新掛，故排除），本支是查詢用的（要查得到掛著已停用標籤的**歷史課程**）。用錯會讓
    舊課程從此搜不到，而畫面上不會有任何異常。
    """
    return await _service.list_filter_tags(db)


@router.get(
    "/courses/filter-owners",
    response_model=list[OwnerOption],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def list_filter_owners(
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
    q: Annotated[str | None, Query(max_length=100)] = None,
    tag_id: Annotated[int | None, Query(ge=1, le=MAX_BIGINT)] = None,
    unit_tag_id: Annotated[int | None, Query(ge=1, le=MAX_BIGINT)] = None,
) -> list[OwnerOption]:
    """ET01「全部課程」的建立者下拉（#648）：整個母體的建立者，**不分頁**。

    篩選參數與 `GET /courses` 同名同上限，但**不收 `owner_id`、`page`、`limit`**——
    選項要列出所有建立者，且不得隨翻頁改變。

    ⚠️ 與 `/courses/filter-tags` 同樣是字面路徑，必須宣告在 `/courses/{course_id}` 之前。
    """
    return await _service.list_filter_owners(
        db, actor_id=ctx.user_id, keyword=q, tag_id=tag_id, unit_tag_id=unit_tag_id
    )


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


@router.put(
    "/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # #301：原本只有 router-level 的 `get_et_context`（任一 ET 角色即可，而學員角色於帳號
    # 建立時自動授予、人人皆有）＋ service 的 `ensure_owner`。缺口是「教師角色被停用但仍是
    # OWNER_ID」——`ensure_owner` 對他放行，於是他不能關閉自己的課（`close` 有角色閘），
    # 卻還能編輯與刪除它。同 router 內 POST / publish / close / reopen / add_chapter 皆已有閘。
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def update_course(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: CourseUpdateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更新基本資料與受訓對象（全量覆寫，帶課程 `version` 檢核樂觀鎖）。"""
    await _service.update_basic(db, course_id, req, operator=operator)


@router.delete(
    "/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # #301：同 `update_course`——`ensure_owner` 擋不住「教師角色已停用但仍是 OWNER_ID」者。
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
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
    # ET-13：本端點自 #303 起會對**全班在籍學員**各寄一封 `COURSE_UPDATE`，成了一個
    # 群發放大面——N 無上界、觸發成本卻只是一次 POST。故補上兩道：
    #
    # 1. **角色閘**：原本只有 router-level 的 `get_et_context`（任一 ET 角色即可，而學員
    #    角色人人自動有）＋ service 的 `ensure_owner`。教師角色被停用是離職 / 轉調的標準
    #    第一步，但只要帳號仍 ACTIVE、`OWNER_ID` 仍是他，他就還能新增章節並觸發群發。
    #    （`PUT`/`DELETE /courses/{id}` 等同型缺口屬既有行為，已登記於 #301。）
    # 2. **限流**：自建分桶，**不併入 `_status_rate_limit`**——那個桶的門檻是照「一天按
    #    不到 5 次」設的，而「儲存並繼續新增」是連續操作，併進去會誤擋。
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_chapter_rate_limit],
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
    chapter_id: Annotated[int, Path(ge=-MAX_BIGINT, le=MAX_BIGINT)],  # 負數＝暫存新增（#631）
    req: ChapterRenameReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """更名章節（帶章節自身之 `version`）。"""
    await _service.rename_chapter(db, chapter_id, req, operator=operator)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(
    chapter_id: Annotated[int, Path(ge=-MAX_BIGINT, le=MAX_BIGINT)],  # 負數＝暫存新增（#631）
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
    chapter_id: Annotated[int, Path(ge=-MAX_BIGINT, le=MAX_BIGINT)],  # 負數＝暫存新增（#631）
    req: ItemCreateReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ItemRow:
    """新增章節項目（教材 / 測驗），追加至最末；同交易內建立對應之空殼內容。"""
    return await _service.add_item(db, chapter_id, req, operator=operator)


@router.put("/chapters/{chapter_id}/items/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_items(
    chapter_id: Annotated[int, Path(ge=-MAX_BIGINT, le=MAX_BIGINT)],  # 負數＝暫存新增（#631）
    req: ItemReorderReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """重排章節內項目順序（送完整順序陣列；帶**章節層** `version`）。"""
    await _service.reorder_items(db, chapter_id, req, operator=operator)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: Annotated[int, Path(ge=-MAX_BIGINT, le=MAX_BIGINT)],  # 負數＝暫存新增（#631）
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
    "/courses/{course_id}/content/apply",
    response_model=ContentUpdateResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def apply_course_content(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ContentUpdateResult:
    """ET05「更新」：把已發布課程的編輯整批生效給學員（#631）。

    已發布課程的內容編輯先存進暫存區，學員看到的是上一次「更新」時的版本。本端點
    **跑與發布完全相同的十項檢核**，通過才整批生效。

    未通過回 422 `ET_PUBLISH_001` + `blockers`（形狀與 `publish` / `reopen` 共用，
    前端沿用 #558 的缺漏清單與紅框），且**活表一行都不會動**——學員端維持上一版。

    暫存區是空的時回 `applied_count = 0`，是安全的 no-op：那代表自上次更新以來沒有
    任何編輯，對一門內容未變的課程回 422 會讓教師以為自己弄壞了什麼。

    > ⚠️ 草稿課程不走這條路（409 `ET_COURSE_010`）——草稿沒有學員，內容不需版本化，
    > 它的生效入口是「發布」。
    """
    return await _publish_service.update_published(db, course_id, operator=operator)


@router.delete(
    "/courses/{course_id}/content/stage",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def discard_course_content(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ET05「取消」：放棄尚未更新的編輯，回到學員目前看到的版本（#631）。

    暫存模式讓編輯工作階段有兩個出口：按「更新」套用，或按「取消」放棄。**活表一行
    都不會動**——學員在整個編輯期間看到的始終是上一次「更新」的版本，所以放棄不需要
    任何回滾。

    暫存區本來就是空的時一樣回 204（冪等）：教師沒改過任何東西就按取消是正常操作。

    > ⚠️ 草稿課程不走這條路（409 `ET_COURSE_010`）——草稿的章節與項目直接寫活表，
    > 沒有暫存表可清，按「取消」本來就不還原。
    """
    await _publish_service.discard_content(db, course_id, operator=operator)


@router.delete(
    "/courses/{course_id}/content/stage/survey",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def discard_survey_edits(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ET05「放棄問卷的編輯」：只丟掉課後問卷的暫存編輯，其餘內容保留（#712）。

    問卷一旦有填答就不可改題。而「更新」會再檢核一次暫存的問卷結構是否與已生效版本
    相同——**任何一次題目編輯都會讓它永遠不同**（選項是全量覆寫，識別碼換新），所以
    編輯期間一出現填答，整門課的「更新」就卡死，章節與測驗的編輯一起出不去。

    本端點把問卷還原成已生效的那一版，讓「更新」過得去，而**其餘編輯一個字都不動**。

    > 在它之前唯一的出路是「取消」，那會丟掉整門課這一輪的全部編輯。

    暫存區本來就是空的時一樣回 204（冪等）。⚠️ 草稿課程回 409 `ET_COURSE_010`。
    """
    await _publish_service.discard_survey_edits(db, course_id, operator=operator)


@router.post(
    "/courses/{course_id}/content/draft",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def keep_course_draft(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ET05「儲存草稿」（已關閉課程）：把這一輪的編輯留著，**不對學員生效**（#720）。

    已關閉課程的動作列是「取消｜儲存草稿｜更新並重開課」。中間這顆是給「半成品先存著、
    下次再弄」用的：**不跑發布檢核**（2026-10-19 裁示），學員唯讀回看的仍是關閉前的內容。

    > 🔴 已發布課程**沒有**這顆鈕（同日裁示）。它的內容隨時對學員生效，多一個「存著不發」
    > 的狀態會讓教師以為自己已經處理完了。回 409 `ET_COURSE_011`。

    沒有這顆鈕按過的暫存樹，教師下次進編輯頁時會被 `content/stage/unkept` 丟掉。
    """
    await _publish_service.keep_draft(db, course_id, operator=operator)


@router.delete(
    "/courses/{course_id}/content/stage/unkept",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN)), *_status_rate_limit],
)
async def discard_unkept_stage(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """ET05 進入編輯頁時呼叫：丟掉**沒按過「儲存草稿」**的暫存殘留（#720）。

    「沒按更新就離開 ＝ 放棄本次全部編輯」這個保證，光靠前端攔截離開是**假的**——
    關分頁、當機、斷線都繞得過去。殘留最糟的不是它存在，而是教師看不出那是殘留。

    冪等：沒有暫存區、或暫存區已被標記保留時，一樣回 204 而不做任何事。
    草稿課程**靜默略過**（不回 409）——前端對所有狀態一律呼叫本支，為草稿回錯誤只會
    逼前端去判斷狀態，而那個判斷遲早與後端分岔。
    """
    await _publish_service.discard_unkept(db, course_id, operator=operator)


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
