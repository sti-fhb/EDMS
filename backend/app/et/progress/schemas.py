"""ET05 學習進度（US5 / #274）schema。"""

from pydantic import BaseModel, Field, model_validator

#: 單次上報之區段數上限（**請求大小防護，非業務規則**）。
#:
#: 正常一次離開頁面最多幾十段（`pause` / `seeked` / `ended` 各一）。設界限是不讓單一
#: 請求塞進上萬段——`data-model` 明訂「不限區段筆數」指的是**表中累計**不裁切，
#: 不是單一請求可以無限大。
MAX_SEGMENTS_PER_REQUEST = 200


class SegmentInput(BaseModel):
    """一段實際播放過的影片時間軸範圍。

    ⚠️ **`start_sec` / `end_sec` 必須是影片時間軸（`currentTime`）而非牆鐘時間**——
    這是「2 倍速看完全片 = 100%」（FR-07）成立的前提。後端不知道也不需要知道倍速。
    """

    start_sec: int = Field(ge=0)
    end_sec: int = Field(ge=0)

    @model_validator(mode="after")
    def _end_after_start(self) -> "SegmentInput":
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec 須大於 start_sec")
        return self


class IntervalReportReq(BaseModel):
    """上報播放區段（可批次）。

    Attributes:
        last_position_sec: 上報當下的播放位置，供下次續看。與區段分開傳——學員暫停在
            某處但那一段尚未結束時，位置仍應更新。
    """

    segments: list[SegmentInput] = Field(min_length=1, max_length=MAX_SEGMENTS_PER_REQUEST)
    last_position_sec: int | None = Field(default=None, ge=0)


class VideoProgress(BaseModel):
    """單支影片之進度（上報 / normalize 後回傳）。"""

    video_id: int
    coverage_pct: int
    last_position_sec: int | None
    completed: bool


class ItemViewedResult(BaseModel):
    """文件 / 說明文字項目「開啟即完成」之結果。"""

    item_id: int
    completed: bool
