"""ET05 學習進度 API（US5 / #274）——區段上報、normalize、項目檢視。

router-level 掛 `get_et_context`（任一 ET 角色）與兩個維度的限流；真正的授權在 service
的四道守門（在籍 OR 擁有者 → 預覽靜默 → 關閉擋寫 → 未解鎖擋下），見 `service` 模組
docstring。

## 為何上報是 POST 而非 PUT

區段是**追加**語意——每段播放一列，不覆寫既有資料。`ET_PROGRESS_INTERVAL` 刻意
不設唯一約束（同一區間可重複播放）。

## 為何 normalize 是獨立端點

normalize 要 DELETE + INSERT 該影片的全部區段。放進上報路徑等於把 O(n) 的寫入塞進
全站最高頻的呼叫裡——而它只在離開頁面時需要做一次。

## 本模組**不寫稽核日誌**（與「CUD 皆須稽核」規範的明示例外）

⚠️ **主要理由是鎖，不是資料量**：`AuditLogService.log_action` 以**單一固定 key** 的
`pg_advisory_xact_lock` 序列化稽核鏈的「讀前列 → 插入」臨界區（見
`dp/audit/repository.py`），且該鎖持有至呼叫方**整個外層交易**結束。把它掛在全站
呼叫頻率最高的端點上，等於讓每一次暫停 / 跳轉都去搶一把全域鎖——排隊的不只是 ET，
是**所有模組**的稽核寫入。

其次才是訊噪比：一次正常觀看會產生數十次呼叫，逐次寫入會讓真正該被看見的管理事件
淹沒在學習流量裡。

> 這**不是**比照 `enrollment` 對 `ET_ENROLL_001` 的處理。那條是「防枚舉」——加入課程
> 成功時仍照常寫稽核，只有查無邀請碼的失敗路徑刻意不寫。本模組略過的是成功寫入路徑
> 本身，性質不同，不可互相援引。

學習軌跡完整保存在三張進度表中，且 `ET_ENROLLMENT.LAST_ACTIVITY_AT` 記錄最後活動
時間——追溯需求由那些表滿足。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.core.rate_limit import RATE_WINDOW_SECONDS, SlidingWindowRateLimiter, rate_limit_by_ip
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import get_et_context, rate_limit_by_et_user
from app.et.progress.schemas import IntervalReportReq, ItemViewedResult, VideoProgress
from app.et.progress.service import EtProgressService

#: 每位使用者每分鐘之進度寫入次數（三個端點合計）。
#:
#: 正常觀看一支影片一分鐘內頂多十幾次（`pause` / `seeked` / `ended` 各一，加上切換項目
#: 的 `viewed`），拖動進度條密集時前端已用 2 秒緩衝收斂。120 遠高於任何正常操作。
#:
#: **必要性**：`ET_PROGRESS_INTERVAL` 每次上報最多追加 200 列，且 `_recompute` 每次都要
#: 把該影片的全部區段載入排序——放任重複呼叫，成本是二次成長的。服務端另有
#: `_MAX_INTERVAL_ROWS` 的累計上界（`service.py`）作為第二道。
_PROGRESS_RATE_MAX = 120

#: 同一 IP 每分鐘之合計上限。刻意寬鬆——同一 NAT 出口可能有數十人同時上課；本維度的
#: 作用是擋住「多開帳號線性放大」，不是管制個別使用者。
_PROGRESS_IP_RATE_MAX = 900

_progress_limiter = SlidingWindowRateLimiter(max_requests=_PROGRESS_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)
_progress_ip_limiter = SlidingWindowRateLimiter(max_requests=_PROGRESS_IP_RATE_MAX, window_seconds=RATE_WINDOW_SECONDS)

#: 三端點**共用同一個分桶**——它們是同一件事（累積學習進度）的三個面，分開計數會讓
#: 實際額度變成三倍，而註解上的門檻只寫一份。比照 `enrollment` 的 `_ENROLL_SCOPE`。
_PROGRESS_SCOPE = "et-progress"

router = APIRouter(
    prefix="/api/et",
    tags=["et-progress"],
    dependencies=[
        Depends(get_et_context),
        Depends(rate_limit_by_et_user(_progress_limiter, _PROGRESS_SCOPE)),
        Depends(rate_limit_by_ip(_progress_ip_limiter, _PROGRESS_SCOPE)),
    ],
)
_service = EtProgressService()


@router.post("/videos/{video_id}/intervals", response_model=VideoProgress)
async def report_intervals(
    video_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    req: IntervalReportReq,
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> VideoProgress:
    """上報播放區段並回傳重算後的覆蓋率（AC 1）。

    區段須為**影片時間軸**（`currentTime`）而非牆鐘時間——2 倍速看完全片 = 100%
    （FR-07）由此成立，後端不需要知道倍速。

    Raises:
        AppError: 404 `ET_LEARN_001` 查無影片或無權；409 `ET_PROGRESS_001` 課程已關閉；
            422 `ET_PROGRESS_002` 全部區段都落在影片長度之外。
    """
    return await _service.report_intervals(db, video_id, req, operator=operator)


@router.post("/videos/{video_id}/normalize", response_model=VideoProgress)
async def normalize_intervals(
    video_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> VideoProgress:
    """離開頁面時合併重疊 / 相接區段並回寫覆蓋率（AC 2）。

    ⚠️ 這是**儲存壓縮**，不是正確性前提：覆蓋率一律先聯集再算，沒跑成功只是列數變多
    （AC 3 / AC 4 因此自然成立）。
    """
    return await _service.normalize(db, video_id, operator=operator)


@router.post("/items/{item_id}/viewed", response_model=ItemViewedResult)
async def mark_item_viewed(
    item_id: Annotated[int, Path(ge=1, le=MAX_BIGINT)],
    operator: OperatorInfo = Depends(get_operator),
    db: AsyncSession = Depends(get_db),
) -> ItemViewedResult:
    """記錄「正在看這一項」，並對純文件 / 說明文字項目標記完成（AC 10 / AC 11）。

    兩件事合在同一個端點：切換項目時前端本來就要呼叫一次，拆成兩支只會讓前端在每次
    切換時打兩個請求，而它們寫的是同一列的相鄰欄位。

    **含影片的教材不會因此被標記完成**——那類由覆蓋率決定（80%），否則點一下就能跳過。
    """
    return await _service.mark_item_viewed(db, item_id, operator=operator)
