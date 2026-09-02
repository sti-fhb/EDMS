import { screen } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

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
})
