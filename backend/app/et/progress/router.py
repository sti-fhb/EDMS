"""ET05 學習進度 API（US5 / #274）——區段上報、normalize、項目檢視。

router-level 只掛 `get_et_context`（任一 ET 角色）；真正的授權在 service 的三道守門
（在籍 OR 擁有者 → 預覽靜默 → 關閉擋寫），見 `service` 模組 docstring。

## 為何上報是 POST 而非 PUT

區段是**追加**語意——每段播放一列，不覆寫既有資料。`ET_PROGRESS_INTERVAL` 刻意
不設唯一約束（同一區間可重複播放）。

## 為何 normalize 是獨立端點

normalize 要 DELETE + INSERT 該影片的全部區段。放進上報路徑等於把 O(n) 的寫入塞進
全站最高頻的呼叫裡——而它只在離開頁面時需要做一次。

## 本模組**不寫稽核日誌**

進度上報是**學習遙測**，不是管理行為：一次正常觀看會產生數十次呼叫（每次
`pause` / `seeked` / `ended` 各一），逐次寫入 `DP_AUDIT_LOG` 會讓稽核表被學習流量
淹沒，真正該被看見的管理事件反而找不到。

比照 `enrollment/service.py` 對 `ET_ENROLL_001` 的同一判斷（該處亦刻意不逐次寫稽核，
理由是枚舉流量會灌爆稽核表）。學習軌跡本身完整保存在三張進度表中，且
`ET_ENROLLMENT.LAST_ACTIVITY_AT` 記錄最後活動時間——稽核需求由那些表滿足。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.operator import OperatorInfo, get_operator
from app.et.course.schemas import MAX_BIGINT
from app.et.deps import get_et_context
from app.et.progress.schemas import IntervalReportReq, ItemViewedResult, VideoProgress
from app.et.progress.service import EtProgressService

router = APIRouter(
    prefix="/api/et",
    tags=["et-progress"],
    dependencies=[Depends(get_et_context)],
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
