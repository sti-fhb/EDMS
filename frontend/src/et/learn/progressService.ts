import { http } from "../../services/http"
import type { Segment } from "./playbackTracker"

/** 單支影片之進度（對齊後端 `app/et/progress/schemas.py::VideoProgress`）。 */
export interface VideoProgress {
  video_id: number
  coverage_pct: number
  last_position_sec: number | null
  completed: boolean
}

/** 項目「開啟即完成」之結果。 */
export interface ItemViewedResult {
  item_id: number
  completed: boolean
}

/**
 * ET05 學習進度 API（US5 / #274）。
 *
 * ## 三支都可能在「離開頁面」的路徑上被呼叫
 *
 * 故一律 fire-and-forget、**失敗不打擾學員**——進度上報失敗的正確處置是下次再送，
 * 不是跳一個他當下無法處理的錯誤。唯一的例外是課程關閉（`ET_PROGRESS_001`），那條
 * 由呼叫端判斷是否提示。
 *
 * 後端的覆蓋率一律先聯集再算，故重送同一段不會灌水（AC 9）——這讓 fire-and-forget
 * 是安全的。
 */
export const progressApi = {
  /** 上報播放區段（可批次，單次上限 200 段）。 */
  reportIntervals: async (
    videoId: number,
    segments: Segment[],
    lastPositionSec: number | null,
  ): Promise<VideoProgress> => {
    const { data } = await http.post<VideoProgress>(`/et/videos/${videoId}/intervals`, {
      segments,
      last_position_sec: lastPositionSec,
    })
    return data
  },

  /**
   * 離開頁面時合併重疊 / 相接區段並回寫覆蓋率。
   *
   * ⚠️ **這是儲存壓縮，不是正確性前提**——沒送成功只是後端的列數變多，覆蓋率照樣正確
   * （AC 3 / AC 4）。故不必為它加重試或 `sendBeacon`。
   */
  normalize: async (videoId: number): Promise<VideoProgress> => {
    const { data } = await http.post<VideoProgress>(`/et/videos/${videoId}/normalize`)
    return data
  },

  /** 記錄「正在看這一項」；純文件 / 說明文字項目一併標記完成。 */
  markViewed: async (itemId: number): Promise<ItemViewedResult> => {
    const { data } = await http.post<ItemViewedResult>(`/et/items/${itemId}/viewed`)
    return data
  },
}
