"""ET03 線下考核核可 API（US16 / #352）＋ ET10 核可查詢（US17 / #385）。

router-level 掛 `require_et_roles(ET_TEACHER, ET_ADMIN)`；擁有權另由 service 的
`ensure_owner_or_admin` 判定（`FR-ET-US16-07`：owner 或管理者）。兩層都要：角色閘擋掉
學員，擁有權閘擋掉「別的教師」。

## 限流**刻意獨立計數**，不與 `et-tracking` 共用

雖然本模組的端點與 ET03 三區塊在同一個畫面上，配額仍分開（`_SCOPE = "et-approval"`，
另建一對 limiter）。兩者的性質不同：tracking 是唯讀查詢，教師頻繁切換課程與展開區塊，
一次操作可能打好幾支，故 180/分；核可是**寫入**，而且一個請求最多觸發 100 封信，值得
比照寫入類端點單獨設限（60/分）。

共用一份的話，兩種行為會互相吃額度——教師只是多看幾次清單就可能把核可的配額耗掉，
而那是他真正需要能送出的動作。

⚠️ **US17 的兩支查詢端點沿用同一個 `et-approval` 分桶**（60/分），這是刻意的取捨：
60 次/分對一個要打字才送出的查詢很寬鬆，而為了限流另開一個 router 只會讓「核可相關的
端點在哪個檔」多一個答案。代價是大量查詢會吃掉核可的額度——若日後真的撞到，再拆。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.pagination import PagedResponse, PaginatedResult
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.approval.query_service import EtApprovalQueryService
from app.et.approval.schemas import ApprovalQueryRow, ApproveReq, ApproveResult, MyApprovalRow, RevokeReq
from app.et.approval.service import EtApprovalService
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user, require_et_roles
from app.et.roles.authz import ET_ADMIN, ET_TEACHER

#: 寫入型端點，比 ET03 的查詢緊得多——核可是逐筆寄信的動作，一次批次最多 100 人。
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
    | `NOT_COMPLETED` | 尚未線上完課 | 單筆 `ET-MSG-ET03-304` / 批次 `ET-MSG-ET03-303` |
    | `ALREADY_APPROVED` | 已有未撤銷的核可紀錄 | `ET-MSG-ET03-309` |
    | `NOT_ENROLLED` | 已不在此課程 | `ET-MSG-ET03-310` |

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

    以 `version` 樂觀鎖檢核：不符回 409 `ET_APPROVAL_004`（`ET-MSG-ET03-308`
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


# ── ET10 核可查詢（US17 / #385）──────────────────────────────────────────────


@router.get(
    "/approvals",
    response_model=PagedResponse[ApprovalQueryRow],
    dependencies=[Depends(require_et_roles(ET_TEACHER, ET_ADMIN))],
)
async def search_approvals(
    user_name: Annotated[str, Query(min_length=1, max_length=50)],
    result: Annotated[str | None, Query(pattern="^(PASS|FAIL)$")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResult[ApprovalQueryRow]:
    """依學員姓名查核可紀錄（`FR-ET-US17-01`）。

    **可見範圍依 SA Q1 裁示 C 分流**（見 `query_rules.visible_clause`）：教師看得到
    全部課程的「通過且未撤銷」，但「不通過」與「已撤銷」僅限自己 owner 的課程；
    管理者不受限。

    ⚠️ 教師視角的前端 MUST 常駐提示「不通過與已撤銷的紀錄僅顯示您所開設的課程」
    ——那是本裁示的配套。少了它，教師看到某門課沒出現時會分不清是「還沒考」還是
    「考了沒過」。

    `user_name` **必填**（SA Q2 裁示 A）：`min_length=1` 擋空字串，全空白由 service
    的 `strip()` 擋下回 422。

    Raises:
        AppError: 422 `ET_APPROVAL_006` 姓名為空白；403 `ET_AUTH_001` 非教師 / 管理者。
    """
    return await _query.search(
        db,
        actor_id=ctx.user_id,
        roles=ctx.roles,
        user_name=user_name,
        result=result,
        page=page,
        limit=limit,
    )


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
