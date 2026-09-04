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

describe("ET05 影片播放器", () => {
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
      setCurrentTime(video, 120)
      fireEvent.timeUpdate(video)
      fireEvent.pause(video)

      await waitFor(() => expect(reportIntervals).toHaveBeenCalledTimes(1))
      expect(reportIntervals).toHaveBeenCalledWith(500, [{ start_sec: 0, end_sec: 120 }], 120)
    })

    it("課程已關閉時完全不上報（AC 12）", async () => {
      // #255 裁示 Q2：讀照舊、寫全停。後端也會擋（409），但每次暫停都打一個註定失敗的
      // 請求是白費的——而且學員會在 devtools 看到一排紅色。
      const { video } = await mountedVideo(true)

      setCurrentTime(video, 0)
      fireEvent.play(video)
      setCurrentTime(video, 120)
      fireEvent.timeUpdate(video)
      fireEvent.pause(video)

      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(reportIntervals).not.toHaveBeenCalled()
    })

    it("拉進度條到結尾不會把跳過的範圍算成看過（AC 7）", async () => {
      const { video } = await mountedVideo()

      setCurrentTime(video, 0)
      setPaused(video, false) // jsdom 不實作播放，`paused` 需自行設定
      fireEvent.play(video)
      setCurrentTime(video, 10)
      fireEvent.timeUpdate(video)
      setCurrentTime(video, 600) // 拖到接近結尾
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
      setCurrentTime(video, 120)
      fireEvent.timeUpdate(video)
      fireEvent.pause(video)

      expect(await screen.findByText(/完成 20%/)).toBeInTheDocument()
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
      setCurrentTime(video, 250)
      fireEvent.timeUpdate(video)
      unmount()

      await waitFor(() => expect(reportIntervals).toHaveBeenCalled())
      expect(reportIntervals).toHaveBeenCalledWith(500, [{ start_sec: 100, end_sec: 250 }], 250)
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
function setCurrentTime(video: HTMLVideoElement, seconds: number) {
  Object.defineProperty(video, "currentTime", { value: seconds, configurable: true, writable: true })
}

/** 同上：jsdom 的 `paused` 恆為 true，而 `seeked` 需要它分辨「播放中拖動」與「暫停中拖動」。 */
function setPaused(video: HTMLVideoElement, paused: boolean) {
  Object.defineProperty(video, "paused", { value: paused, configurable: true, writable: true })
}
