import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy }
})

import { EtMyCoursesPage } from "./MyCoursesPage"
import type { MyCoursesResult } from "./myCoursesSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 覆寫我的課程回應（空清單 / 特定狀態）。 */
function mockMyCourses(body: MyCoursesResult) {
  server.use(http.get("/api/et/my-courses", () => HttpResponse.json(body)))
}

describe("ET04 我的課程", () => {
  it("統計卡顯示五項數字（AC 2 + #363）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    // wireframe 只畫了三張（缺「未開始」），以 AC 2 為準補為四張；#363 再加「尚未開放」。
    expect(await screen.findByText("已加入課程")).toBeInTheDocument()
    expect(screen.getByText("進行中")).toBeInTheDocument()
    expect(screen.getByText("未開始")).toBeInTheDocument()
    expect(screen.getByText("已完成")).toBeInTheDocument()
    // #363：與「未開始」**並存且不同義**——前者是「還沒開放」，後者是「已開放、還沒開始學」。
    expect(screen.getByText("尚未開放")).toBeInTheDocument()
  })

  it("課程卡片顯示名稱、標籤、章節數與閱課期間（AC 3）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.getByText("護理師")).toBeInTheDocument()
    expect(screen.getByText("軍人")).toBeInTheDocument()
    expect(screen.getByText(/5 章節/)).toBeInTheDocument()
    // **每一張**卡片都要有閱課期間（含尚未開放者）。與卡片數比較而非寫死數字——
    // 原本寫死 2，#363 在 fixture 加第三張卡時就因此轉紅，而那與本斷言的用意無關。
    const cardCount = document.querySelectorAll(".MuiCard-root").length
    expect(cardCount).toBeGreaterThan(1)
    expect(screen.getAllByText(/閱課期間/)).toHaveLength(cardCount)
  })

  it("期間已過者即使 status 仍是 PUBLISHED 也顯示「已關閉」（#288）", async () => {
    // 卡片看後端算好的 `is_closed`，不自己判 `status === "CLOSED"`。到期自動轉 CLOSED
    // 屬 ET-16（未實作），所以「status=PUBLISHED 但 is_closed=true」是常態而非過渡狀態。
    // 若前端改回判 status，這張卡會標成「已發布」，而學員點進去 ET05 是唯讀的——
    // 兩個畫面在使用者眼前互相矛盾。
    mockMyCourses({
      summary: { joined: 1, in_progress: 0, not_started: 1, completed: 0, pending_open: 0 },
      courses: [
        {
          course_id: 9,
          course_name: "期間已過的課程",
          status: "PUBLISHED",
          is_closed: true,
          is_pending_open: false,
          completion_status: "NOT_STARTED",
          tags: ["全體"],
          chapter_count: 2,
          open_start_at: "2026-01-01T00:00:00Z",
          open_end_at: "2026-02-01T00:00:00Z",
          progress_pct: 0,
        },
      ],
    })
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText("期間已過的課程")).toBeInTheDocument()
    expect(screen.getByText("已關閉")).toBeInTheDocument()
  })

  it("尚未開放的課程出現在清單且不可點擊（#363）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    // 預設 fixture 第三張是 is_pending_open: true
    expect(await screen.findByText("輸血反應辨識與處理")).toBeInTheDocument()

    // 卡片不可點擊：不渲染 CardActionArea，所以整張卡沒有 button 角色
    const card = screen.getByText("輸血反應辨識與處理").closest(".MuiCard-root")
    expect(card).not.toBeNull()
    expect(card!.querySelector("button")).toBeNull()
    expect(card!.querySelector(".MuiCardActionArea-root")).toBeNull()
  })

  it("尚未開放的卡片標開放時點，且**不顯示**完課狀態（#363）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    const card = (await screen.findByText("輸血反應辨識與處理")).closest(".MuiCard-root")!
    const text = card.textContent ?? ""

    // 學員真正需要的那一件事：要等到什麼時候
    expect(text).toMatch(/將於.+開放學習/)
    // ⛔ 不可出現「未開始」——`completion_status` 必為 NOT_STARTED，但學員此刻不可能
    // 開始學。同一個詞指兩件事正是本 issue 要消除的誤讀。
    expect(text).not.toContain("未開始")
    expect(text).toContain("尚未開放")
    // 進度條對還不能開始的課程只是雜訊
    expect(card.querySelector(".MuiLinearProgress-root")).toBeNull()
    expect(text).not.toContain("完成 0%")
  })

  it("已開放的課程仍可點擊進入（#363 不得回歸）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtMyCoursesPage />)

    await user.click(await screen.findByText("採血作業新進人員訓練"))

    expect(navigateSpy).toHaveBeenCalled()
  })

  it("已關閉課程顯示「已關閉」標示（AC 5）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText("血品安全與品保概論")).toBeInTheDocument()
    expect(screen.getByText("已關閉")).toBeInTheDocument()
  })

  it("無任何課程時顯示空狀態提示", async () => {
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }, courses: [] })
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText(/尚未加入任何課程/)).toBeInTheDocument()
  })

  it("整頁無任何「退出課程」入口（AC 11 / FR-ET-US4-06）", async () => {
    renderWithProviders(<EtMyCoursesPage />)
    await screen.findByText("採血作業新進人員訓練")

    // 學員無主動退出能力——退場僅能由教師於 US9 執行「移除學員」。
    // 後端連端點都沒有，前端自然也不該有入口。
    expect(screen.queryByRole("button", { name: /退出|離開課程|移除/ })).not.toBeInTheDocument()
  })

  it("提供加入新課程入口", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByRole("button", { name: "加入新課程" })).toBeInTheDocument()
  })

  it("已加入之課程只顯示一則提示，不被後續訊息蓋掉（AC 10）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "採血作業新進人員訓練",
          owner_name: "王教師",
          chapter_count: 5,
          already_joined: true,
          open_start_at: null,
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtMyCoursesPage />)

    await user.click(await screen.findByRole("button", { name: "加入新課程" }))
    await user.type(screen.getByLabelText(/邀請碼/), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // AC 10：#255 起 ET05 已存在，「已加入」改為**直接導向該課程**而非給訊息。
    // （在此之前是兩則 message.info 互相覆蓋，實測時顯示成「章節學習頁尚未開放」。）
    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses/1/learn"))
    expect(screen.queryByText("章節學習頁尚未開放")).not.toBeInTheDocument()
  })

  it("已加入但課程尚未開放時，提示要說明接下來該做什麼（#363 改文案）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({
          course_id: 9,
          course_name: "尚未開放的課",
          owner_name: "王教師",
          chapter_count: 2,
          already_joined: true,
          open_start_at: "2099-01-01T09:00:00Z",
        }),
      ),
    )
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }, courses: [] })
    const user = userEvent.setup()
    renderWithProviders(<EtMyCoursesPage />)

    await user.click(await screen.findByRole("button", { name: "加入新課程" }))
    await user.type(screen.getByLabelText(/邀請碼/), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // 實測回報：只說「您已加入此課程」，學員不知道接下來該做什麼。裁示 A 的提示原本
    // 只做在「新加入」那條路徑，漏了「已加入 + 未開放」這個組合。
    //
    // ⚠️ #363 改了文案：原本說「將於課程開放後**出現於清單**」，那是清單會過濾掉未開放
    // 課程時代的說法，現在課程就在清單上（標「尚未開放」）——留著會叫學員去等一件已經
    // 發生的事。
    expect(await screen.findByText(/課程開放後即可開始學習/)).toBeInTheDocument()
    expect(screen.queryByText(/出現於清單/)).not.toBeInTheDocument()
  })
})

describe("ET04 邀請連結 / QR Code 帶入邀請碼（#273）", () => {
  it("網址帶 ?code= 時自動開啟加入視窗並預填該碼", async () => {
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }, courses: [] })
    renderWithProviders(<EtMyCoursesPage />, undefined, ["/et/my-courses?code=83052617"])

    // 教師「複製邀請連結」與 QR Code 都指向這個網址；學員落地後不該還要自己重打 8 碼
    expect(await screen.findByDisplayValue("83052617")).toBeInTheDocument()
  })

  it("預填後**不自動送出**——AC 8 的預覽是明訂的一步", async () => {
    let previewCalled = false
    server.use(
      http.post("/api/et/enrollments/preview", () => {
        previewCalled = true
        return HttpResponse.json({
          course_id: 7,
          course_name: "採血作業新進人員訓練",
          owner_name: "王教師",
          chapter_count: 2,
          already_joined: false,
          open_start_at: null,
        })
      }),
    )
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }, courses: [] })
    renderWithProviders(<EtMyCoursesPage />, undefined, ["/et/my-courses?code=83052617"])

    expect(await screen.findByDisplayValue("83052617")).toBeInTheDocument()
    expect(previewCalled).toBe(false)
    expect(screen.getByRole("button", { name: "查詢" })).toBeEnabled()
  })

  it("網址沒有 code 時不自動開啟視窗", async () => {
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }, courses: [] })
    renderWithProviders(<EtMyCoursesPage />)

    await screen.findByRole("button", { name: "加入新課程" })
    expect(screen.queryByLabelText(/邀請碼/)).not.toBeInTheDocument()
  })
})
