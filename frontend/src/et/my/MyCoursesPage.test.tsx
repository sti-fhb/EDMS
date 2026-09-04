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
  it("統計卡顯示四項數字（AC 2）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    // 「已加入 2、進行中 1、未開始 1、已完成 0」——四項皆須呈現。
    // wireframe 只畫了三張（缺「未開始」），此處以 AC 2 為準。
    expect(await screen.findByText("已加入課程")).toBeInTheDocument()
    expect(screen.getByText("進行中")).toBeInTheDocument()
    expect(screen.getByText("未開始")).toBeInTheDocument()
    expect(screen.getByText("已完成")).toBeInTheDocument()
  })

  it("課程卡片顯示名稱、標籤、章節數與閱課期間（AC 3）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.getByText("護理師")).toBeInTheDocument()
    expect(screen.getByText("軍人")).toBeInTheDocument()
    expect(screen.getByText(/5 章節/)).toBeInTheDocument()
    // 兩張卡片都有閱課期間——用 getAllByText，`getByText` 會因找到多個而失敗。
    expect(screen.getAllByText(/閱課期間/)).toHaveLength(2)
  })

  it("已關閉課程顯示「已關閉」標示（AC 5）", async () => {
    renderWithProviders(<EtMyCoursesPage />)

    expect(await screen.findByText("血品安全與品保概論")).toBeInTheDocument()
    expect(screen.getByText("已關閉")).toBeInTheDocument()
  })

  it("無任何課程時顯示空狀態提示", async () => {
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0 }, courses: [] })
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

  it("已加入但課程尚未開放時，提示要說明清單為何是空的", async () => {
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
    mockMyCourses({ summary: { joined: 0, in_progress: 0, not_started: 0, completed: 0 }, courses: [] })
    const user = userEvent.setup()
    renderWithProviders(<EtMyCoursesPage />)

    await user.click(await screen.findByRole("button", { name: "加入新課程" }))
    await user.type(screen.getByLabelText(/邀請碼/), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // 實測回報：只說「您已加入此課程」而清單是空的（AC 4），學員會以為系統壞了。
    // 裁示 A 的提示原本只做在「新加入」那條路徑，漏了「已加入 + 未開放」這個組合。
    expect(await screen.findByText(/將於課程開放後出現於清單/)).toBeInTheDocument()
  })
})
