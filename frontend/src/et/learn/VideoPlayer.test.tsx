import { fireEvent, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { VideoPlayer } from "./VideoPlayer"
import type { MaterialVideoRow } from "./learnSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const { requestVideoTicket } = vi.hoisted(() => ({ requestVideoTicket: vi.fn() }))
vi.mock("./learnService", async (orig) => {
  const actual = await orig<typeof import("./learnService")>()
  return { ...actual, requestVideoTicket }
})

const { reportIntervals, normalize } = vi.hoisted(() => ({ reportIntervals: vi.fn(), normalize: vi.fn() }))
vi.mock("./progressService", () => ({ progressApi: { reportIntervals, normalize, markViewed: vi.fn() } }))

const VIDEO: MaterialVideoRow = {
  video_id: 500,
  file_name: "採血示範.mp4",
  duration_sec: 615,
  sort_order: 1,
  coverage_pct: 0,
  last_position_sec: null,
}

beforeEach(() => {
  requestVideoTicket.mockReset()
  requestVideoTicket.mockResolvedValue("ticket-1")
  reportIntervals.mockReset()
  reportIntervals.mockResolvedValue({ video_id: 500, coverage_pct: 20, last_position_sec: 120, completed: false })
  normalize.mockReset()
  normalize.mockResolvedValue({ video_id: 500, coverage_pct: 20, last_position_sec: 120, completed: false })
})

function renderPlayer(rates = [0.75, 1, 1.25, 1.5, 2], video: MaterialVideoRow = VIDEO, readOnly = false) {
  return renderWithProviders(<VideoPlayer video={video} playbackRates={rates} readOnly={readOnly} />)
}

describe("ET06 影片播放器", () => {
  it("取票後才設 src（AC 3）", async () => {
    const { container } = renderPlayer()

    await waitFor(() => expect(container.querySelector("video")).toBeInTheDocument())
    expect(container.querySelector("video")?.getAttribute("src")).toContain("t=ticket-1")
  })

  it("倍速選項由後端給，不在前端寫死（AC 4）", async () => {
    // 後端已依 `ET_VIDEO_PLAYBACK_MAX_RATE` 限縮；前端照列即可。
    // 傳三段代表參數被調低的情形——前端不得自行補回五段。
    renderPlayer([0.75, 1, 1.25])

    expect(await screen.findByLabelText("播放速度")).toBeInTheDocument()
    expect(screen.queryByText("2x")).not.toBeInTheDocument()
  })

  it("票過期導致播放失敗時自動重取票並換上新 URL", async () => {
    // 這是 code review HIGH 的修法：`<video>` 對同一 URL 會反覆發出請求
    //（按下播放才抓內容、久停續播、拖到未緩衝區段），票過期就會失敗。
    // 只拉長 TTL 不算修好——把頁面開著去吃午餐回來按播放一樣會撞到。
    requestVideoTicket.mockResolvedValueOnce("ticket-1").mockResolvedValueOnce("ticket-2")
    const { container } = renderPlayer()
    const video = await waitFor(() => {
      const el = container.querySelector("video")
      expect(el).toBeInTheDocument()
      return el as HTMLVideoElement
    })

    fireEvent.error(video)

    await waitFor(() => expect(container.querySelector("video")?.getAttribute("src")).toContain("t=ticket-2"))
    expect(requestVideoTicket).toHaveBeenCalledTimes(2)
  })

  it("重取票後仍失敗只提示一次，不無限重試", async () => {
    requestVideoTicket.mockResolvedValue("ticket-1")
    const { container } = renderPlayer()
    // `waitFor` 內**必須有斷言**，否則第一次就回傳 null（沒有拋錯就不會重試）
    const video = await waitFor(() => {
      const el = container.querySelector("video")
      expect(el).toBeInTheDocument()
      return el as HTMLVideoElement
    })

    fireEvent.error(video)
    await waitFor(() => expect(requestVideoTicket).toHaveBeenCalledTimes(2))
    fireEvent.error(container.querySelector("video") as HTMLVideoElement)

    expect(await screen.findByText(/影片播放失敗/)).toBeInTheDocument()
    // 第二次失敗不再取票——否則是無窮迴圈
    expect(requestVideoTicket).toHaveBeenCalledTimes(2)
  })

  it("重取成功後可再次自動救援（旗標會解除）", async () => {
    // `TICKET_TTL_SECONDS = 300` 的正當性建立在「有自動重取兜底」之上——若一個掛載
    // 週期只能救一次，學員在同一支長影片上第二次撞到過期就得重新整理。
    requestVideoTicket
      .mockResolvedValueOnce("ticket-1")
      .mockResolvedValueOnce("ticket-2")
      .mockResolvedValueOnce("ticket-3")
    const { container } = renderPlayer()
    const video = await waitFor(() => {
      const el = container.querySelector("video")
      expect(el).toBeInTheDocument()
      return el as HTMLVideoElement
    })

    fireEvent.error(video)
    await waitFor(() => expect(container.querySelector("video")?.getAttribute("src")).toContain("t=ticket-2"))
    // 換 src 後瀏覽器會發 loadeddata——旗標於此解除
    fireEvent.loadedData(container.querySelector("video") as HTMLVideoElement)
    fireEvent.error(container.querySelector("video") as HTMLVideoElement)

    await waitFor(() => expect(container.querySelector("video")?.getAttribute("src")).toContain("t=ticket-3"))
    expect(requestVideoTicket).toHaveBeenCalledTimes(3)
  })

  it("取票失敗顯示錯誤而非空白播放器", async () => {
    requestVideoTicket.mockRejectedValue(new Error("403"))
    renderPlayer()

    expect(await screen.findByText(/影片載入失敗/)).toBeInTheDocument()
  })

  describe("進度上報（#274）", () => {
    async function mountedVideo(readOnly = false, video: MaterialVideoRow = VIDEO) {
      const rendered = renderPlayer([1, 2], video, readOnly)
      const el = await waitFor(() => {
        const found = rendered.container.querySelector("video")
        expect(found).toBeInTheDocument()
        return found as HTMLVideoElement
      })
      return { ...rendered, video: el }
    }

    it("播放後暫停會上報該區段（AC 1）", async () => {
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      fireEvent.play(video)
      // 播到 10 秒（< CHECKPOINT_SECONDS）→ 期間不打點，暫停時才送出唯一一段。
      // #609 之前這裡播到 120 秒卻只發一次 timeupdate；改成真實節奏後 120 秒會
      // 觸發 8 次 15 秒打點，不再是「一次呼叫」——縮短播放長度以保留本條的原意。
      playTo(video, 0, 10)
      fireEvent.pause(video)

      await waitFor(() => expect(reportIntervals).toHaveBeenCalledTimes(1))
      expect(reportIntervals).toHaveBeenCalledWith(500, [{ start_sec: 0, end_sec: 10 }], 10)
    })

    it("課程已關閉時完全不上報（AC 12）", async () => {
      // #255 裁示 Q2：讀照舊、寫全停。後端也會擋（409），但每次暫停都打一個註定失敗的
      // 請求是白費的——而且學員會在 devtools 看到一排紅色。
      const { video } = await mountedVideo(true)

      setCurrentTime(video, 0)
      fireEvent.play(video)
      playTo(video, 0, 120)
      fireEvent.pause(video)

      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(reportIntervals).not.toHaveBeenCalled()
    })

    it("拉進度條到結尾不會把跳過的範圍算成看過（AC 7）", async () => {
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      setPaused(video, false) // jsdom 不實作播放，`paused` 需自行設定
      fireEvent.play(video)
      playTo(video, 0, 10)
      // 真實順序：瀏覽器完成 seek 時**先**在新位置發 timeupdate，**再**發 seeked。
      // #609 之前本檔只發 seeked，等於跳過了真正會出錯的那一步。
      setCurrentTime(video, 600) // 拖到接近結尾
      fireEvent.timeUpdate(video)
      fireEvent.seeked(video)
      setPaused(video, true)
      fireEvent.pause(video)

      await waitFor(() => expect(reportIntervals).toHaveBeenCalled())
      const segments = reportIntervals.mock.calls[0][1]
      expect(segments).toEqual([{ start_sec: 0, end_sec: 10 }])
    })

    it("上報後顯示覆蓋率", async () => {
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      fireEvent.play(video)
      playTo(video, 0, 10)
      fireEvent.pause(video)

      expect(await screen.findByText(/完成 20%/)).toBeInTheDocument()
    })

    it("連續播放不暫停時也會持續上報（實測回報：完成度一路卡住）", async () => {
      // `pause` / `seeked` / `ended` 都是「停下來」才觸發。少了播放中的定期打點，學員
      // 從頭播到尾都不暫停時整段觀看在結束前一次都不會上報——畫面上的覆蓋率會停在
      // 進頁時的舊值，而瀏覽器若在播放中被關掉，那整段就永久遺失。
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      setPaused(video, false)
      fireEvent.play(video)
      // 全程只有 timeupdate，沒有任何 pause / seeked / ended
      playTo(video, 0, 32)

      await waitFor(() => expect(reportIntervals).toHaveBeenCalledTimes(2))
      // 相接而不重疊——後端聯集回 [0,30]，與「播完才送一次」等價。
      // ⚠️ #609 之前本條以 5 秒為步長，而那個跨距在真實瀏覽器中只會出現在拖動進度條；
      // 改真實節奏後打點落在 15 / 30 秒整點上。
      expect(reportIntervals.mock.calls[0][1]).toEqual([{ start_sec: 0, end_sec: 15 }])
      expect(reportIntervals.mock.calls[1][1]).toEqual([{ start_sec: 15, end_sec: 30 }])
    })

    it("切換項目（unmount）時仍送出最後一段與正確的續看位置", async () => {
      // **React 在跑 useEffect cleanup 之前就把 DOM ref 設成 null**（passive effect 的
      // 執行順序）。若收尾時讀 `videoRef.current?.currentTime`，會拿到 0：
      //   - `endSegment(tracker, 0)` → 最後那一段被整個丟掉
      //   - `last_position_sec: 0` → 後端覆寫，續看位置被重置（AC 11 壞掉）
      // 而「切換到下一個項目」正是最常見的離開方式。
      const { video, unmount } = await mountedVideo()

      setCurrentTime(video, 100)
      fireEvent.play(video)
      playTo(video, 100, 110) // < CHECKPOINT_SECONDS：期間不打點，最後一段留到 unmount 才送
      unmount()

      await waitFor(() => expect(reportIntervals).toHaveBeenCalled())
      // 第三個參數是續看位置——本條真正要守的是它不會被 ref 已為 null 而寫成 0
      expect(reportIntervals).toHaveBeenCalledWith(500, [{ start_sec: 100, end_sec: 110 }], 110)
    })

    it("切到別的分頁再切回、繼續播放的部分仍計入（#609）", async () => {
      /**
       * 🔴 切走時 `finish()` 把 tracker 設成 `IDLE_TRACKER`（`anchor: null`），但影片在
       * 背景分頁其實沒有停。切回來若不重新起算，之後的 `checkpoint` / `endSegment` /
       * `onEnded` 一律因 `anchor === null` 不產生任何區段——學員看完整支影片也不會完成，
       * 要手動暫停再播放一次才恢復記錄。
       */
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      setPaused(video, false)
      fireEvent.play(video)
      playTo(video, 0, 10)

      // 切走（hidden）→ 收尾並清空 tracker
      setVisibility("hidden")
      fireEvent(document, new Event("visibilitychange"))
      await waitFor(() => expect(reportIntervals).toHaveBeenCalled())
      const callsAfterHidden = reportIntervals.mock.calls.length

      // 切回來（visible），影片仍在播放
      setVisibility("visible")
      fireEvent(document, new Event("visibilitychange"))

      // 之後繼續播放的部分必須被記錄
      playTo(video, 10, 20)
      fireEvent.pause(video)

      await waitFor(() => expect(reportIntervals.mock.calls.length).toBeGreaterThan(callsAfterHidden))
      const after = reportIntervals.mock.calls.slice(callsAfterHidden).flatMap((c) => c[1])
      expect(after).toEqual([{ start_sec: 10, end_sec: 20 }])
    })

    it("有上次位置時載入後定位過去（AC 11）", async () => {
      const { video } = await mountedVideo(false, { ...VIDEO, last_position_sec: 300 })

      fireEvent.loadedMetadata(video)

      expect(video.currentTime).toBe(300)
    })

    it("上次看到最後一秒者不定位，否則一按播放就結束", async () => {
      const { video } = await mountedVideo(false, { ...VIDEO, last_position_sec: 615 })

      fireEvent.loadedMetadata(video)

      expect(video.currentTime).toBe(0)
    })
  })
})

/** jsdom 不實作播放，`currentTime` 需自行設定才會被事件處理器讀到。 */
/**
 * 模擬**連續播放**到 `to`：每步前進 1 影片秒並發一次 `timeupdate`。
 *
 * 🔴 **不可寫成「設 `currentTime = to` 後只發一次 `timeUpdate`」**（#609 之前本檔的
 * 寫法）。真瀏覽器播放期間 `timeupdate` 每秒約觸發 4 次，一次跳 120 秒在真實情境中
 * 只會發生在「使用者拖動了進度條」——而 #609 之後 `checkpoint` 正是以位置是否連續
 * 來分辨這兩者。沿用舊寫法等於把每一次正常播放都偽裝成跳躍。
 *
 * 步長取 1 秒（門檻為 `playbackRate * 1.5`）：既在門檻內，事件數又只有 0.25 秒步長的
 * 四分之一。
 */
function playTo(video: HTMLVideoElement, from: number, to: number) {
  for (let t = from + 1; t <= to; t += 1) {
    setCurrentTime(video, t)
    fireEvent.timeUpdate(video)
  }
  if (video.currentTime !== to) {
    setCurrentTime(video, to)
    fireEvent.timeUpdate(video)
  }
}

/** jsdom 的 `document.visibilityState` 唯讀，需自行覆寫才能模擬切分頁。 */
function setVisibility(state: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true })
}

function setCurrentTime(video: HTMLVideoElement, seconds: number) {
  Object.defineProperty(video, "currentTime", { value: seconds, configurable: true, writable: true })
}

/** 同上：jsdom 的 `paused` 恆為 true，而 `seeked` 需要它分辨「播放中拖動」與「暫停中拖動」。 */
function setPaused(video: HTMLVideoElement, paused: boolean) {
  Object.defineProperty(video, "paused", { value: paused, configurable: true, writable: true })
}
