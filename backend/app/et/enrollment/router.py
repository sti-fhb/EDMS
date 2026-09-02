"""ET04 我的課程與加入新課程 API（US4 / #247）。

router-level 只掛 `get_et_context`，**不掛 `require_et_roles(ET_STUDENT)`**——ET 學員
角色於帳號建立當下即自動授予、存量帳號亦由 bootstrap seed 回填（`deps.py` 已載明），
故加掛學員角色不會擋掉任何人，只會讓讀者以為這裡有實質授權。

真正的授權在資料本身：所有查詢都以 `ctx.user_id` 過濾，沒有「查別人的課程」的參數
可傳。

## 為何 preview 是 POST 而非 GET

邀請碼是憑證。放在 query string 會進 access log、瀏覽器歷史與 Referer；
即使沒有寫入，它也不該出現在 URL 裡。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.deps import EtContext, get_et_context
from app.et.enrollment.schemas import JoinByCodeReq, JoinPreview, JoinResult, MyCoursesResult
from app.et.enrollment.service import EtEnrollmentService

router = APIRouter(
    prefix="/api/et",
    tags=["et-enrollment"],
    dependencies=[Depends(get_et_context)],
)
_service = EtEnrollmentService()


@router.get("/my-courses", response_model=MyCoursesResult)
async def my_courses(
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> MyCoursesResult:
    """ET04 我的課程：四項統計 + 課程卡片清單。

    起始時間未到之課程不出現（AC 4）；已關閉課程仍出現並帶 `status=CLOSED`（AC 5）。
    """
    return await _service.my_courses(db, user_id=ctx.user_id)


@router.post("/enrollments/preview", response_model=JoinPreview)
async def preview_enrollment(
    req: JoinByCodeReq,
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> JoinPreview:
    """驗證邀請碼並回課程資訊，**不寫入**（AC 6）。

    已加入者以 `already_joined=true` 表示（200），非錯誤——那是正常導航（AC 10）。
    """
    return await _service.preview(db, code=req.invitation_code, user_id=ctx.user_id)


@router.post("/enrollments", response_model=JoinResult, status_code=status.HTTP_201_CREATED)
async def join_course(
    req: JoinByCodeReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> JoinResult:
    """確認加入課程，`JOIN_SOURCE = INVITATION_CODE`（AC 7）。

    **重跑 `preview` 的全部驗證**——預覽是體驗，不是把關。
    """
    return await _service.join(db, code=req.invitation_code, operator=operator)
