import { screen, waitFor } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { EtOverviewWidget } from "./EtOverviewWidget"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 只回指定的卡，其餘為 `null`（＝沒有該角色）。 */
function mockDashboard(body: Record<string, unknown>) {
  server.use(
    http.get("/api/et/dashboard", () =>
      HttpResponse.json({ student: null, teacher: null, admin: null, ...body }),
    ),
  )
}

const EMPTY_STUDENT = { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }

describe("首頁教育訓練概況", () => {
  it("三張卡皆有資料時依「管理者 → 教師 → 學員」順序呈現（#89 決策 3）", async () => {
    renderWithProviders(<EtOverviewWidget enabled />)

    await screen.findByText("教育訓練概況")
    const titles = screen.getAllByText(/全體訓練概況|我的課程待辦|我的學習概況/).map((el) => el.textContent)
    expect(titles).toEqual(["全體訓練概況", "我的課程待辦", "我的學習概況"])
  })

  /**
   * 🔴 #89 的空卡規則——本測試是它唯一的守門。
   *
   * > spec 定義「人人具 ET 學員預設角色」，若嚴格「有 ET 角色就顯示我的課程」→
   * > **主管也會看到空的「我的課程」**。故規則為卡片無資料就不渲染。
   *
   * 也就是說：`student` 不是 `null`（他確實有學員角色），但 `joined === 0`，不可渲染。
   */
  it("有學員角色但沒選課時不渲染學員卡（#89 空卡規則）", async () => {
    mockDashboard({ student: EMPTY_STUDENT })
    renderWithProviders(<EtOverviewWidget enabled />)

    await waitFor(() => expect(screen.queryByText("我的學習概況")).not.toBeInTheDocument())
    expect(screen.queryByText("教育訓練概況")).not.toBeInTheDocument()
  })

  it("教師沒有待辦時不渲染教師卡", async () => {
    mockDashboard({ teacher: { ending_soon: [], draft_count: 0 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    await waitFor(() => expect(screen.queryByText("我的課程待辦")).not.toBeInTheDocument())
  })

  it("只有草稿沒有即將截止也算有待辦——那是「卡在我這」的訊號", async () => {
    mockDashboard({ teacher: { ending_soon: [], draft_count: 2 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    expect(await screen.findByText("我的課程待辦")).toBeInTheDocument()
    expect(screen.getByText(/門課程尚未發布/)).toBeInTheDocument()
  })

  it("三張卡皆無資料時整個 widget 不渲染，不留空標題", async () => {
    mockDashboard({ student: EMPTY_STUDENT, teacher: { ending_soon: [], draft_count: 0 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    await waitFor(() => expect(screen.queryByText("教育訓練概況")).not.toBeInTheDocument())
  })

  it("未啟用時完全不發查詢——端點對無 ET 角色者回 403", async () => {
    let called = 0
    server.use(
      http.get("/api/et/dashboard", () => {
        called += 1
        return HttpResponse.json({ student: null, teacher: null, admin: null })
      }),
    )
    renderWithProviders(<EtOverviewWidget enabled={false} />)

    await waitFor(() => expect(screen.queryByText("教育訓練概況")).not.toBeInTheDocument())
    expect(called).toBe(0)
  })

  it("今天到期的課程標示與其他天數不同", async () => {
    mockDashboard({
      teacher: {
        ending_soon: [
          { course_id: 1, course_name: "今天到期的課", days_left: 0, not_completed: 3 },
          { course_id: 2, course_name: "還有兩天的課", days_left: 2, not_completed: 1 },
        ],
        draft_count: 0,
      },
    })
    renderWithProviders(<EtOverviewWidget enabled />)

    expect(await screen.findByText("今天到期")).toBeInTheDocument()
    expect(screen.getByText("剩 2 天")).toBeInTheDocument()
  })

  it("管理者卡的各單位依後端給的順序呈現，前端不重排", async () => {
    mockDashboard({
      admin: {
        overdue_incomplete: 0,
        completion_rate: "50.00",
        by_unit: [
          { tag_name: "低分單位", enrolled: 2, completed: 0, completion_rate: "0.00" },
          { tag_name: "高分單位", enrolled: 2, completed: 2, completion_rate: "100.00" },
        ],
      },
    })
    renderWithProviders(<EtOverviewWidget enabled />)

    await screen.findByText("全體訓練概況")
    // ⚠️ 不可用 /單位/ 查——那會先抓到區塊標題「各單位達成率（低者在前）」。
    const units = screen.getAllByText(/分單位/).map((el) => el.textContent ?? "")
    expect(units.map((t) => t.replace(/[^一-鿿]/g, ""))).toEqual([
      "低分單位人",
      "高分單位人",
    ])
  })
})
