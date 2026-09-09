"""ET06 測驗作答 API（US6 / #279）——學員端。

router-level 掛 `get_et_context`（任一 ET 角色）；真正的授權在 service 的四道守門
（反查鏈 → 在籍 OR 擁有者 → 項目已解鎖 → 尚有次數），見 `service` 模組 docstring。

## 為何暫存是 PUT

同一題重複暫存是**覆寫**語意（`UQ(ATTEMPT_ID, QUESTION_ID)`），冪等。學員在同一題上
改三次答案不該產生三筆紀錄。

## 本模組不寫稽核日誌——**這是 spec 明訂的，不是取捨**

`docs/specs/et/spec.md` §稽核來源功能碼的結語寫得很清楚：

> 一般資料異動之建立者 / 異動者與時間由各表標準稽核欄位承載，**不逐筆寫
> `DP_AUDIT_LOG`**；僅上表所列之權限、破例與關鍵狀態變更寫入。

而那張表**沒有學員作答**——與測驗有關的只有 `ET-QUIZ-RESET`（教師重置重考次數，屬
破例動作，US9）。學員作答是一般資料異動，由 `ET_QUIZ_ATTEMPT_M` / `_D` 的標準稽核欄位
承載；那兩張表 append-only、永不刪除，且比稽核日誌更完整（連每一題選了什麼都在）。

> 附帶一提，即使沒有這條規定，把稽核掛在暫存端點上也是錯的：`log_action` 以**單一固定
> key** 的 `pg_advisory_xact_lock` 序列化稽核鏈並持有至整個外層交易，而暫存是每切一題
> 就呼叫一次——排隊的會是**所有模組**的稽核寫入。但那只是佐證，真正的依據是上面那條。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.attempt.schemas import AnswerReq, AttemptResult, AttemptState, QuizIntro
from app.et.attempt.service import EtAttemptService
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import EtContext, get_et_context, rate_limit_by_et_user

#: 每位使用者每分鐘之作答相關請求數。
#:
#: 正常作答一分鐘內頂多切幾題（每切一題一次暫存），120 遠高於任何正常操作。限流的對象
#: 是「反覆呼叫開始作答」——每次成功都會建立一筆 attempt 與整組 `_D` 明細列。
_ATTEMPT_RATE_MAX = 120
_ATTEMPT_IP_RATE_MAX = 900

_limiter = SlidingWindowRateLimiter(max_requests=_ATTEMPT_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_ip_limiter = SlidingWindowRateLimiter(max_requests=_ATTEMPT_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_SCOPE = "et-attempt"

router = APIRouter(
    prefix="/api/et",
    tags=["et-attempt"],
    dependencies=[
        Depends(get_et_context),
        Depends(rate_limit_by_et_user(_limiter, _SCOPE)),
        Depends(rate_limit_by_ip(_ip_limiter, _SCOPE)),
    ],
)
_service = EtAttemptService()


@router.get("/quizzes/{quiz_id}/intro", response_model=QuizIntro)
async def quiz_intro(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> QuizIntro:
    """引導頁：題數、及格分數、時限、剩餘次數、上次與最高成績（AC 1）。

    `time_limit_min` 為 `null` 代表**不限時**——前端須顯示「不限時」而非「0 分」。
    """
    return await _service.intro(db, quiz_id, user_id=ctx.user_id)


@router.post("/quizzes/{quiz_id}/attempts", response_model=AttemptState, status_code=status.HTTP_201_CREATED)
async def start_attempt(
    quiz_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> AttemptState:
    """開始作答：建立 attempt、凍結快照、洗牌（AC 3 / AC 4）。

    **已有未完成的作答時回既有那一筆**（`resumed=true`），不建新的、不吃次數
    （#279 SA 裁示 Q1 = A）。

    Raises:
        AppError: 404 `ET_ATTEMPT_001` 查無 / 無權 / 項目尚未解鎖；
            409 `ET_ATTEMPT_002` 重考次數已用完；409 `ET_ATTEMPT_006` 課程已關閉。
    """
    return await _service.start(db, quiz_id, operator=operator)


@router.get("/attempts/{attempt_id}", response_model=AttemptState)
async def attempt_state(
    attempt_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> AttemptState:
    """取作答狀態：依快照順序的題目、已暫存答案、剩餘秒數（AC 5）。

    `remaining_sec` 由後端自 `STARTED_AT` 推導——**中途離開仍持續扣時間**（wireframe
    引導頁明訂），故不可由前端每次載入重新起算。
    """
    return await _service.state(db, attempt_id, user_id=ctx.user_id)


@router.get("/attempts/{attempt_id}/result", response_model=AttemptResult)
async def attempt_result(
    attempt_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    ctx: EtContext = Depends(get_et_context),
    db: AsyncSession = Depends(get_db),
) -> AttemptResult:
    """取**已提交** attempt 的成績與逐題明細（複習用）。

    分數不重算——提交當下已寫入，重算等於不信任閱卷結果。尚未提交者回 404，與「不存在」
    「非本人」共用同一回應。

    ⚠️ 該狀態守門擋的是「**這一次**作答的答案在作答中被取回」。它**擋不到**「另開視窗查
    **上一次**作答的答案卷」——測驗不抽題，上一次的答案卷逐題適用於這一次。那條路徑由
    前端的「離開作答視窗即自動提交」處理（`spec_us6` 2026-09-09 裁示），本端點不是它的
    安全邊界，別把這裡當成唯一防線。
    """
    return await _service.result(db, attempt_id, user_id=ctx.user_id)


@router.put("/attempts/{attempt_id}/answers/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def save_answer(
    attempt_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    question_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: AnswerReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> None:
    """暫存單題作答（切換題目時觸發）。空清單為合法輸入——學員可以取消勾選。

    **逾時後拒收**（409 `ET_ATTEMPT_005`）——否則時限完全沒有強制力：關掉分頁、慢慢查完
    資料再回來逐題寫入即可滿分。提交本身不受此限（見 `submit`）。
    """
    await _service.save_answer(db, attempt_id, question_id, req, operator=operator)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptResult)
async def submit_attempt(
    attempt_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> AttemptResult:
    """提交並即時自動閱卷，回總分 / 及格 / 逐題明細（AC 7～11）。

    **逾時不拒收**——記為 `TIMEOUT` 但照常計分（AC 6）。及格時回寫項目完成，
    下一項 / 下一章隨之解鎖（AC 12）。
    """
    return await _service.submit(db, attempt_id, operator=operator)
