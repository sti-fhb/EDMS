"""ET02 線下考核核可 API（US16 / #352）＋ ET04 核可查詢（US17 / #385）。

router-level 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`；擁有權另由 service 的
`ensure_owner_or_admin` 判定（owner ∪ 管理者）。兩層都要：角色閘擋掉學員，擁有權閘擋掉
「別的教師」。

⚠️ `FR-ET-US16-07` 已於 #463 改訂為「**UI 執行者**限 owner」，後端授權刻意未收窄——
本段描述的是後端，仍然正確；但別據以認為管理者在畫面上做得到核可（他沒有入口）。

## 限流**刻意獨立計數**，不與 `et-tracking` 共用

雖然本模組的端點與 ET02 三區塊在同一個畫面上，配額仍分開（`_SCOPE = "et-approval"`，
另建一對 limiter）。兩者的性質不同：tracking 是唯讀查詢，教師頻繁切換課程與展開區塊，
一次操作可能打好幾支，故 180/分；核可是**寫入**，而且一個請求最多觸發 100 封信，值得
比照寫入類端點單獨設限（60/分）。

共用一份的話，兩種行為會互相吃額度——教師只是多看幾次清單就可能把核可的配額耗掉，
而那是他真正需要能送出的動作。

⚠️ **US17 的兩支查詢端點沿用同一個 `et-approval` 分桶**（60/分），這是刻意的取捨：
為了限流另開一個 router 只會讓「核可相關的端點在哪個檔」多一個答案。代價是大量查詢
會吃掉核可的額度——若日後真的撞到，再拆。

🔴 **不要把這個額度當成防列舉的控制**。60 req/min × `limit=100` 意味著單分鐘可取回
6000 列；以常見姓氏逐一查詢，數千人規模的核可紀錄一分鐘內就掃得完。真正在收斂列舉的是
另外兩件事，調整任何一項前請先想清楚：

1. **母體限制**：只回「有 `ET_APPROVAL` 列的人」，不是全員名冊（`DP_USER` 的全域搜尋在
   `/api/dp/users`，掛 `require_any_module_admin()`，教師拿不到）
2. **角色受控**：`ET_TEACHER` 由管理者指派，非自助取得

⚠️ 另需知道的事實：`POST /approvals/search` 是 ET **第一支讓非管理者教師讀到無關課程學員資料**
的端點（既有的 `tracking` / `reports` 全部走 owner 過濾）。SA 裁示 C 已接受這個暴露面，
但它是新的，不是沿用。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse, PaginatedResult
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.approval.query_service import EtApprovalQueryService
from app.et.approval.schemas import (
    ApprovalCourseOption,
    ApprovalQueryRow,
    ApprovalSearchReq,
    ApproveReq,
    ApproveResult,
    MyApprovalRow,
    RevokeReq,
)
from app.et.approval.service import EtApprovalService
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

#: 寫入型端點，比 ET02 的查詢緊得多——核可是逐筆寄信的動作，一次批次最多 100 人。
_USER_RATE = 60
_IP_RATE = 200

_SCOPE = "et-approval"

_user_limiter = SlidingWindowRateLimiter(max_requests=_USER_RATE, window_seconds=RATE_WINDOW_SECONDS)
_ip_limiter = SlidingWindowRateLimiter(max_requests=_IP_RATE, window_seconds=RATE_WINDOW_SECONDS)

router = APIRouter(
    prefix="/api/et",
    tags=["ET 線下核可"],
    dependencies=[
        Depends(get_et_context),
        Depends(rate_limit_by_et_user(_user_limiter, _SCOPE)),
        Depends(rate_limit_by_ip(_ip_limiter, _SCOPE)),
    ],
)

_service = EtApprovalService()
_query = EtApprovalQueryService()


@router.post(
    "/courses/{course_id}/approvals",
    response_model=ApproveResult,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def approve(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    payload: ApproveReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> ApproveResult:
    """核可一位或多位學員為「通過」/「不通過」（`FR-ET-US16-04` / `-05`）。

    **單筆即 `user_ids` 長度為 1**——與批次共用同一支端點，否則「跳過」會有兩種回應
    格式，而前端得對同一個動作維護兩套解析。

    回應的 `skipped` 逐筆帶理由，三種各有不同的下一步：

    | 理由 | 意義 | 前端訊息 |
    |---|---|---|
    | `NOT_COMPLETED` | 尚未線上完課 | 單筆 `ET-MSG-ET02-304` / 批次 `ET-MSG-ET02-303` |
    | `ALREADY_APPROVED` | 已有未撤銷的核可紀錄 | `ET-MSG-ET02-309` |
    | `NOT_ENROLLED` | 已不在此課程 | `ET-MSG-ET02-310` |

    **只有 PASS 寄 `APPROVAL_PASSED` 通知**；FAIL 不寄（`FR-ET-US16-08`）。
    寄信失敗不回滾核可——紀錄已是業務事實，學員於 US17 核可查詢看得到。
    """
    return await _service.approve(
        db,
        course_id,
        payload,
        actor_id=ctx.user_id,
        actor_roles=ctx.roles,
        operator=operator,
    )


@router.post(
    "/courses/{course_id}/approvals/{user_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def revoke(
    course_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    user_id: Annotated[str, Path(min_length=1, max_length=20)],
    payload: RevokeReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
) -> Response:
    """撤銷核可（`FR-ET-US16-06`）——**原因必填**，撤銷後綜合狀態回「待核可」。

    以 `version` 樂觀鎖檢核：不符回 409 `ET_APPROVAL_004`（`ET-MSG-ET02-308`
    「核可狀態已被其他人變更，請重新整理後再試」）。

    ⚠️ **撤銷是 POST 不是 DELETE**：它不刪除任何東西——那一列仍在，只是 `IS_REVOKED`
    翻成 true 並記下原因與執行者，而且之後還能重新核可（同一列 update）。用 DELETE
    會讓人以為紀錄消失了。

    **不寄信**（`FR-ET-US16-08`）：撤銷需要教師當面說明，不該由系統自動發一封信。
    """
    await _service.revoke(
        db,
        course_id,
        user_id,
        payload,
        actor_id=ctx.user_id,
        actor_roles=ctx.roles,
        operator=operator,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── ET04 核可查詢（US17 / #385）──────────────────────────────────────────────


@router.post(
    "/approvals/search",
    response_model=PagedResponse[ApprovalQueryRow],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def search_approvals(
    req: ApprovalSearchReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResult[ApprovalQueryRow]:
    """依學員**姓名或 Email** 查核可紀錄（`FR-ET-US17-01`、#436）。

    ## 🔴 為何是 POST 而且查詢條件走 body（#391）

    `keyword` 必定是一個人的姓名或 Email（兩者皆為個資），而 **URL 會被 nginx `error_log` 與 Cloudflare 的
    請求日誌記下來**（前者格式不可自訂、後者不在本系統掌控範圍）。改走 body 之後，
    那兩處只看得到 `/api/et/approvals/search`。完整背景見 `ApprovalSearchReq` 的 docstring。

    ⚠️ **這是一個不寫入的 POST。** 專案規則要求「寫入型 API 一律注入 `OperatorInfo`
    填寫 `CREATED_*`」，本端點**刻意不注入**——它不寫任何資料，用 POST 的唯一理由是
    上述的日誌問題，語意仍是讀取。

    🔴 **不寫稽核日誌這件事，#439 之後理由已經不夠了。** 原本的理由是「它不寫任何資料」，
    而當時一次查詢 ≈ 一個已知姓名、讀取量小。現在「不給關鍵字、一次取回整門課的通過
    名單」是**被鼓勵的主要用法**，單筆讀取的個資體積上升一到兩個數量級，而稽核軌跡仍是
    零——事後無法回答「是誰、在什麼時候、整批取走了哪一門課的名單」。對照 DM：下載有稽核。

    ⛔ 所以「它不寫資料所以不用稽核」現在只說明了**為什麼不用 `OperatorInfo`**，不足以
    單獨支撐「不記讀取事件」。

    ⚠️ **目前沒有 issue 在追這件事**（2026-09-30 使用者裁示：只記在此，不另開 follow-up）。
    要補的話形狀是：對「未給關鍵字的 course-only 查詢」記一筆讀取事件
    （`actor_id` + `course_id` + 回傳筆數，**不記任何姓名 / Email**）。寫在這裡是因為
    下一個讀這段 docstring 的人，正是有理由重新考慮它的人。

    ⛔ 路徑用 `/approvals/search` 而非 `POST /approvals`：後者在語意上是「建立一筆
    核可」，而建立核可已經是 `POST /courses/{course_id}/approvals`。不讓兩個 POST
    在同一個名詞上表示相反的事。

    **可見範圍依 SA Q1 裁示 C 分流**（見 `query_rules.visible_clause`）：教師看得到
    全部課程的「通過且未撤銷」，但「不通過」與「已撤銷」僅限自己 owner 的課程；
    管理者不受限。

    ⚠️ 教師視角的前端 MUST 常駐提示「不通過與已撤銷的紀錄僅顯示您所開設的課程」
    ——那是本裁示的配套。少了它，教師看到某門課沒出現時會分不清是「還沒考」還是
    「考了沒過」。

    ## 關鍵字與課程「至少給一個」（#439，取代 SA Q2 裁示 A 的關鍵字必填）

    | 給的條件 | 結果 |
    |---|---|
    | 只給課程 | 該課程的核可紀錄——解決「不知道有誰可以查」 |
    | 只給關鍵字 | 跨課程查那個人（**#439 之前的行為，未改變**）|
    | 兩者皆給 | 交集 |
    | 兩者皆不給 | 422 `ET_APPROVAL_006` |

    🔴 **非管理者只能給自己開設的課程**，否則 403 `ET_APPROVAL_007`。前端下拉只列得出
    自己的課，這道閘是**防繞過**：少了它，教師可以用 `{course_id: 別人的課}` 一次撈出
    該課全部通過者的名單而不需要知道任何名字——那是裁示 A 要擋的東西以課程為單位重演。

    Raises:
        AppError: 422 `ET_APPROVAL_006` 關鍵字與課程皆未給；403 `ET_APPROVAL_007`
            非管理者以他人課程篩選；403 `ET_AUTH_001` 非教師 / 管理者。
    """
    return await _query.search(
        db,
        actor_id=ctx.user_id,
        roles=ctx.roles,
        keyword=req.keyword,
        course_id=req.course_id,
        result=req.result,
        page=req.page,
        limit=req.limit,
    )


@router.get(
    "/approvals/filter-courses",
    response_model=list[ApprovalCourseOption],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def approval_filter_courses(
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalCourseOption]:
    """ET04 課程篩選下拉的選項——**有核可紀錄的**課程（#439）。

    教師只取得自己開設的課，管理者不限。⚠️ 這與 `search` 的擁有權閘是**一組的**：
    下拉決定使用者選得到什麼，那道閘決定 API 收不收——只做前者等於沒做。

    ## ⛔ 不要改成沿用 ET01 的課程清單（`GET /et/courses`）

    看起來是同一件事，但兩支的母體都不對：

    | `scope` | 為何不能用 |
    |---|---|
    | `all` | 只給「已發布**且期間未過**」，而核可紀錄絕大多數落在**已結束**的課程上 |
    | `mine` | 對管理者毫無意義（他多半沒有自己的課），下拉會是空的 |

    `all` 的後果尤其安靜：管理者會發現最相關的課全部不在下拉裡，而畫面不會說明任何事。

    ⚠️ **不分頁**：這是下拉，母體是核可紀錄（不隨課程總數成長），與
    `GET /et/tags`、`/et/courses/filter-tags` 同一形狀。日後若真的長到需要分頁，
    該做的是改成可搜尋的自動完成，不是給下拉加 `page`。
    """
    return await _query.filter_courses(db, actor_id=ctx.user_id, roles=ctx.roles)


@router.get("/approvals/mine", response_model=PagedResponse[MyApprovalRow])
async def my_approvals(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResult[MyApprovalRow]:
    """學員自查：自己**已通過（有效未撤銷）**的課程（`FR-ET-US17-03`）。

    🔴 **不收任何 `user_id` 參數**——對象一律取自 token 的 `ctx.user_id`。
    `FR-ET-US17-04`「學員竄改參數查他人」因此在介面上就沒有可竄改的參數，而不是靠
    一道判斷式擋下；多帶的 query param 會被 FastAPI 忽略。

    只掛 `get_et_context` 不掛角色閘：兼具教師身分者也是學員，這條路徑對他照常可用。
    """
    return await _query.mine(db, actor_id=ctx.user_id, page=page, limit=limit)
