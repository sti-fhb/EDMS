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

## 限流：使用者維度 + IP 維度，比照其餘 ET 學員端寫入端點

⚠️ **初版曾以「都要在籍 + 完課才過得去、送出另有唯一約束擋重複」為由不掛限流，那個
判斷是錯的**，security review 指出三個破洞：

1. **唯一約束只約束成功的寫入。** 失敗路徑（422 作答不合規、409 已填 / 已關閉）次數
   無上界，而每次失敗前都已經跑完在籍查詢、`entry_facts`、以及 `_completed` 的**兩支
   `GROUP BY` 聚合查詢**——最貴的那兩支排在 `ensure_fillable` 之前。
2. **「完課」不是成本門檻。** 純文件項目的完成是學員自己呼叫 `items/{id}/viewed` 取
   得的，要進到可填狀態幾乎不需要成本。
3. `deps.rate_limit_by_et_user` 的 docstring 明寫「**新端點請一律用本函式**」，而
   `progress/router.py`、`enrollment/router.py` 的學員端寫入端點全都兩個維度都掛。

門檻放得很寬：正常填一份問卷是 1 次 GET + 1 次 POST。它真正的作用是把「無上界的便宜
請求」變成有上界——包括模組層級 `AppError` 實例累積 traceback 那條（見 `service.py`
的工廠函式說明）。
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user
from app.et.survey_fill.schemas import SurveyForm, SurveySubmitReq, SurveySubmitResult
from app.et.survey_fill.service import EtSurveyFillService

#: 同一使用者每分鐘之上限。正常操作是 1 次 GET + 1 次 POST；重載頁面、修正未答題後
#: 重送幾次都在個位數內，30 遠高於任何真實使用。
_SURVEY_FILL_RATE_MAX: Final = 30

#: 同一 IP 每分鐘之合計上限。刻意寬鬆——同一 NAT 出口可能有數十人同時上課；本維度擋的
#: 是「多開帳號線性放大」（自助註冊是開的），不是管制個別使用者。比照 `progress`。
_SURVEY_FILL_IP_RATE_MAX: Final = 300

_survey_fill_limiter = SlidingWindowRateLimiter(max_requests=_SURVEY_FILL_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_survey_fill_ip_limiter = SlidingWindowRateLimiter(
    max_requests=_SURVEY_FILL_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS
)

#: 兩支端點**共用同一個分桶**——它們是同一件事（填一份問卷）的兩個面，分開計數會讓
#: 實際額度變成兩倍，而註解上的門檻只寫一份。比照 `progress` 的 `_PROGRESS_SCOPE`。
_SURVEY_FILL_SCOPE: Final = "et-survey-fill"

router = APIRouter(
    prefix="/api/et",
    tags=["et-survey-fill"],
    dependencies=[
        Depends(get_et_context),
        Depends(rate_limit_by_et_user(_survey_fill_limiter, _SURVEY_FILL_SCOPE)),
        Depends(rate_limit_by_ip(_survey_fill_ip_limiter, _SURVEY_FILL_SCOPE)),
    ],
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
