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

const VIDEO: MaterialVideoRow = {
  video_id: 500,
  file_name: "採血示範.mp4",
  duration_sec: 615,
  sort_order: 1,
}

beforeEach(() => {
  requestVideoTicket.mockReset()
  requestVideoTicket.mockResolvedValue("ticket-1")
})

function renderPlayer(rates = [0.75, 1, 1.25, 1.5, 2]) {
  return renderWithProviders(<VideoPlayer video={VIDEO} playbackRates={rates} />)
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
})
