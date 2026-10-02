import { screen, waitFor } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { EtOverviewWidget } from "./EtOverviewWidget"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/**
 * 只回指定的卡，其餘為 `null`（＝沒有該角色）。回傳一個**已回應**的旗標。
 *
 * 🔴 **negative 斷言一定要先等這個旗標**。`waitFor(() => expect(queryByText(X))
 * .not.toBeInTheDocument())` 會在**第一次輪詢就通過**——而那時查詢還沒回來，畫面
 * 本來就什麼都沒有。少了錨點，那種斷言驗的是「資料還沒到」而不是「空卡不渲染」，
 * 對任何實作都通過。
 *
 * 2026-10-01 以變異證實：把 `if (!student && !teacher && !admin) return null`
 * 改成 `if (false)`（空卡規則整個失效），三條 negative 斷言**全部照樣綠**。
 */
function mockDashboard(body: Record<string, unknown>) {
  const state = { responded: false }
  server.use(
    http.get("/api/et/dashboard", () => {
      state.responded = true
      return HttpResponse.json({ student: null, teacher: null, admin: null, ...body })
    }),
  )
  return state
}

const EMPTY_STUDENT = { joined: 0, in_progress: 0, not_started: 0, completed: 0, pending_open: 0 }

/** 兩門課、完成率一低一高；含 `course_id`（同名課程不合併，前端以它當 key）。 */
const ADMIN = {
  overdue_incomplete: 0,
  completion_rate: "50.00",
  by_course: [
    { course_id: 101, course_name: "低分課程", enrolled: 2, completed: 0, completion_rate: "0.00" },
    { course_id: 102, course_name: "高分課程", enrolled: 2, completed: 2, completion_rate: "100.00" },
  ],
}

describe("首頁教育訓練概況", () => {
  it("三張卡皆有資料時依「管理者 → 教師 → 學員」順序呈現（#89 決策 3）", async () => {
    renderWithProviders(<EtOverviewWidget enabled />)

    await screen.findByText("ET 教育訓練概況")
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
    const served = mockDashboard({ student: EMPTY_STUDENT })
    renderWithProviders(<EtOverviewWidget enabled />)

    // 正向錨點：先確認資料真的回來了，否則下方的「不存在」在 t=0 就成立
    await waitFor(() => expect(served.responded).toBe(true))
    expect(screen.queryByText("我的學習概況")).not.toBeInTheDocument()
    expect(screen.queryByText("ET 教育訓練概況")).not.toBeInTheDocument()
  })

  it("教師沒有待辦時不渲染教師卡", async () => {
    const served = mockDashboard({ teacher: { ending_soon: [], draft_count: 0 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    await waitFor(() => expect(served.responded).toBe(true))
    expect(screen.queryByText("我的課程待辦")).not.toBeInTheDocument()
  })

  it("只有草稿沒有即將截止也算有待辦——那是「卡在我這」的訊號", async () => {
    mockDashboard({ teacher: { ending_soon: [], draft_count: 2 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    expect(await screen.findByText("我的課程待辦")).toBeInTheDocument()
    expect(screen.getByText(/門課程尚未發布/)).toBeInTheDocument()
  })

  it("三張卡皆無資料時整個 widget 不渲染，不留空標題", async () => {
    const served = mockDashboard({ student: EMPTY_STUDENT, teacher: { ending_soon: [], draft_count: 0 } })
    renderWithProviders(<EtOverviewWidget enabled />)

    await waitFor(() => expect(served.responded).toBe(true))
    expect(screen.queryByText("ET 教育訓練概況")).not.toBeInTheDocument()
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

    await waitFor(() => expect(screen.queryByText("ET 教育訓練概況")).not.toBeInTheDocument())
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

  it("管理者卡的各課程依後端給的順序呈現，前端不重排", async () => {
    mockDashboard({ admin: ADMIN })
    renderWithProviders(<EtOverviewWidget enabled />)

    await screen.findByText("全體訓練概況")
    // ⚠️ 不可用 /課程/ 查——那會先抓到區塊標題的註記「各課程完成率」。
    // 改查 /分課程/：那兩個字只出現在 fixture 的課程名（低分課程 / 高分課程）裡。
    expect(screen.getAllByText(/分課程/).map((el) => el.textContent)).toEqual(["低分課程", "高分課程"])
  })

  describe("版面與數字呈現（2026-10-02 手測裁示）", () => {
    it("三塊各自在不同的白底卡上，不共用一張", async () => {
      renderWithProviders(<EtOverviewWidget enabled />)

      await screen.findByText("全體訓練概況")
      const papers = ["全體訓練概況", "我的課程待辦", "我的學習概況"].map((title) =>
        screen.getByText(title).closest(".MuiPaper-root"),
      )
      expect(papers.every((p) => p !== null)).toBe(true)
      // 三個不同的節點＝三張卡。共用一張時這裡會是 1。
      expect(new Set(papers).size).toBe(3)
    })

    it("區塊標題下方有分隔線", async () => {
      renderWithProviders(<EtOverviewWidget enabled />)

      await screen.findByText("全體訓練概況")
      const paper = screen.getByText("全體訓練概況").closest(".MuiPaper-root")
      expect(paper?.querySelector(".MuiDivider-root")).not.toBeNull()
    })

    it("「全體訓練概況」後面帶灰色小字註記", async () => {
      renderWithProviders(<EtOverviewWidget enabled />)

      expect(await screen.findByText("各課程完成率")).toBeInTheDocument()
    })

    it("完成率顯示為整數，不帶小數", async () => {
      mockDashboard({ admin: ADMIN })
      renderWithProviders(<EtOverviewWidget enabled />)

      await screen.findByText("全體訓練概況")
      expect(screen.getByText("0%")).toBeInTheDocument()
      expect(screen.getByText("100%")).toBeInTheDocument()
      expect(screen.queryByText(/\d\.\d/)).not.toBeInTheDocument()
    })

    it("🔴 取整數是無條件捨去——99.6% 不可顯示成 100%", async () => {
      // 四捨五入會讓管理者以為那門課全部完訓、停止催辦。與下一條成對：
      // 只有這條的話，把實作寫成「一律捨去到 0」也會通過。
      mockDashboard({
        admin: {
          overdue_incomplete: 0,
          completion_rate: "99.60",
          by_course: [{ course_id: 1, course_name: "快完成的課", enrolled: 250, completed: 249, completion_rate: "99.60" }],
        },
      })
      renderWithProviders(<EtOverviewWidget enabled />)

      await screen.findByText("全體訓練概況")
      expect(screen.getAllByText("99%").length).toBeGreaterThan(0)
      expect(screen.queryByText("100%")).not.toBeInTheDocument()
    })

    it("真正的 100% 仍顯示 100%", async () => {
      mockDashboard({
        admin: {
          overdue_incomplete: 0,
          completion_rate: "100.00",
          by_course: [{ course_id: 1, course_name: "全員完訓", enrolled: 3, completed: 3, completion_rate: "100.00" }],
        },
      })
      renderWithProviders(<EtOverviewWidget enabled />)

      await screen.findByText("全體訓練概況")
      expect(screen.getAllByText("100%").length).toBeGreaterThan(0)
    })

    it("不再顯示「逾期未完成」", async () => {
      const served = mockDashboard({ admin: { ...ADMIN, overdue_incomplete: 7 } })
      renderWithProviders(<EtOverviewWidget enabled />)

      await waitFor(() => expect(served.responded).toBe(true))
      await screen.findByText("全體訓練概況") // 正向錨點：卡片確實渲染了
      expect(screen.queryByText("逾期未完成")).not.toBeInTheDocument()
    })

    it("只有逾期、一門課都沒有時不渲染管理者卡（不留空表格）", async () => {
      // 🔴 與上一條成對。拿掉畫面上的「逾期未完成」之後，`hasAdminData` 若仍保留
      // `|| overdue_incomplete > 0`，這種資料會渲染出一張只有表頭、沒有任何列的表格。
      const served = mockDashboard({ admin: { overdue_incomplete: 7, completion_rate: "0.00", by_course: [] } })
      renderWithProviders(<EtOverviewWidget enabled />)

      await waitFor(() => expect(served.responded).toBe(true))
      expect(screen.queryByText("全體訓練概況")).not.toBeInTheDocument()
      expect(screen.queryByText("ET 教育訓練概況")).not.toBeInTheDocument()
    })
  })
})
