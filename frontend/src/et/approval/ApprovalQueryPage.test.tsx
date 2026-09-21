import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { EtApprovalQueryPage } from "./ApprovalQueryPage"

/**
 * 設定登入者身分——本頁的分流同時取自**兩支端點**，兩支都要覆寫。
 *
 * ⚠️ `capabilities` 決定「教師視角還是學員視角」，`module-summary` 的 `et.is_admin`
 * 決定「教師視角裡要不要顯示範圍提示」。只設前者的話，預設 handler 會讓每個人都是
 * 管理者（`is_admin: true`），教師專屬的提示就永遠測不到。
 */
function asRole(role: "teacher" | "admin" | "student") {
  const canManage = role !== "student"
  server.use(
    http.get("/api/et/courses/capabilities", () =>
      HttpResponse.json({
        can_create_course: role === "teacher",
        can_manage_courses: canManage,
        can_learn: role === "student",
      }),
    ),
    http.get("/api/dp/user/module-summary", () =>
      HttpResponse.json({
        et: { has_role: true, is_admin: role === "admin" },
        dm: { has_role: false, is_admin: false },
      }),
    ),
  )
}

const EMPTY = { data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }

describe("ET10 核可查詢：教師 / 管理者視角", () => {
  it("輸入姓名查詢後列出核可紀錄，含課程、結果、核可人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // fixture 三列同屬林佳蓉，故鎖定其中一列而非全頁比對
    const row = (await screen.findByText("採血作業新進人員訓練")).closest("tr")!
    expect(within(row).getByText("林佳蓉")).toBeInTheDocument()
    expect(within(row).getByText("王主任")).toBeInTheDocument()
    expect(within(row).getByText("通過")).toBeInTheDocument()
  })

  it("已撤銷的紀錄標示已撤銷並列出原因與撤銷人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    const row = (await screen.findByText("血品安全與品保概論")).closest("tr")!
    expect(within(row).getByText("已撤銷")).toBeInTheDocument()
    expect(within(row).getByText(/核可對象誤植/)).toBeInTheDocument()
    expect(within(row).getByText(/李管理員/)).toBeInTheDocument()
  })

  it("🔴 教師視角常駐範圍提示——那是 SA 裁示 C 的配套，不是可選的 UX 潤飾", async () => {
    // 少了它，教師看到某門課沒出現時分不清是「還沒考」還是「考了沒過」。
    // 裁示 C 讓同一張表裡混了兩種範圍，提示是唯一讓教師知道這件事的地方。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    const hint = await screen.findByText(/僅顯示您所開設的課程/)
    expect(hint).toBeInTheDocument()
    // SA 2026-09-21 追加裁示：他人課程的考核備註也被遮蔽，提示必須一併涵蓋——
    // 否則教師看到通過卻沒備註時會以為核可人沒寫，而不是被遮蔽了。
    expect(hint).toHaveTextContent("考核備註")
  })

  it("查無資料顯示空狀態提示（ET-MSG-ET10-001）", async () => {
    asRole("teacher")
    server.use(http.get("/api/et/approvals", () => HttpResponse.json(EMPTY)))
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名"), "查無此人")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("查無符合條件的核可紀錄")).toBeInTheDocument()
  })

  it("姓名未填時不送出請求（SA Q2 裁示 A）", async () => {
    asRole("teacher")
    let called = false
    server.use(
      http.get("/api/et/approvals", () => {
        called = true
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.click(await screen.findByRole("button", { name: "查詢" }))

    expect(await screen.findByText("請輸入學員姓名")).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it("只打空白也視為未填", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名"), "   ")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("請輸入學員姓名")).toBeInTheDocument()
  })

  it("查詢前不顯示空狀態——那會讓人以為已經查過且查無資料", async () => {
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名")
    expect(screen.queryByText("查無符合條件的核可紀錄")).not.toBeInTheDocument()
  })

  it("🔴 查詢失敗顯示錯誤，**不得**渲染成「查無符合條件」", async () => {
    // 本頁的使用情境是排班前確認某人受訓完整與否，「查無紀錄」會被讀成「沒受過訓」
    // ——那是方向最危險的假陰性。最容易撞到的是 429（查詢與核可寫入共用同一個分桶）。
    asRole("teacher")
    server.use(
      http.get("/api/et/approvals", () =>
        HttpResponse.json({ error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試" }, { status: 429 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("操作過於頻繁，請稍後再試")).toBeInTheDocument()
    expect(screen.queryByText("查無符合條件的核可紀錄")).not.toBeInTheDocument()
  })
})

describe("ET10 核可查詢：學員視角", () => {
  it("🔴 載入失敗顯示錯誤，**不得**渲染成「尚無已通過核可的課程」", async () => {
    asRole("student")
    server.use(
      http.get("/api/et/approvals/mine", () =>
        HttpResponse.json({ error_code: "COMMON_500", error_message: "系統發生錯誤" }, { status: 500 }),
      ),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("系統發生錯誤")).toBeInTheDocument()
    expect(screen.queryByText("您目前尚無已通過核可的課程")).not.toBeInTheDocument()
  })

  it("僅顯示自己已通過的課程，且不出現查詢框", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.queryByLabelText("學員姓名")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "查詢" })).not.toBeInTheDocument()
  })

  it("不顯示教師視角的範圍提示", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByText("採血作業新進人員訓練")
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("無已通過課程時顯示空狀態（ET-MSG-ET10-002）", async () => {
    asRole("student")
    server.use(http.get("/api/et/approvals/mine", () => HttpResponse.json(EMPTY)))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("您目前尚無已通過核可的課程")).toBeInTheDocument()
  })
})

describe("ET10 核可查詢：共通", () => {
  it("🔴 任一視角都不得提供下載或列印（FR-ET-US17-05）", async () => {
    // 客戶 2026-07-17 明確確認**不需要**核可證明 / 結業證書。
    for (const role of ["teacher", "student"] as const) {
      asRole(role)
      const { unmount } = renderWithProviders(<EtApprovalQueryPage />)
      await waitFor(() => expect(screen.queryByText("載入中…")).not.toBeInTheDocument())

      for (const name of [/下載/, /列印/, /證明/, /證書/, /匯出/]) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
        expect(screen.queryByText(name)).not.toBeInTheDocument()
      }
      unmount()
    }
  })

  it("管理者視角不顯示教師專屬的範圍提示", async () => {
    // 🔴 管理者沒有範圍限制，對他顯示「僅顯示您所開設的課程」是錯的資訊。
    // ⚠️ 判定來源是 `module-summary.et.is_admin`，不是 `capabilities`——同時具教師與
    // 管理者身分者 `can_create_course` 也是 true，用它推會把他誤判成非管理者。
    asRole("admin")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByLabelText("學員姓名")).toBeInTheDocument()
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("🔴 `module-summary` 未回來前不渲染任何視角——避免管理者閃現不適用的提示", async () => {
    // 只等 `capabilities` 的話，整頁重新載入時它可能先回來，此時 `summary` 還是
    // undefined → `isAdmin` 退回 false → 管理者會**短暫看到**「僅顯示您所開設的課程」。
    // 它會自我修正，但那句是裁示 C 的強制配套，閃現錯誤版本與顯示錯誤版本同樣不可接受。
    server.use(
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: true, can_learn: false }),
      ),
      // 讓 module-summary 慢於 capabilities 回來
      http.get("/api/dp/user/module-summary", async () => {
        await new Promise((r) => setTimeout(r, 80))
        return HttpResponse.json({ et: { has_role: true, is_admin: true }, dm: { has_role: false, is_admin: false } })
      }),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    // capabilities 先回來的那個空窗期：不得已 isAdmin=false 渲染出教師視角
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
    expect(await screen.findByLabelText("學員姓名")).toBeInTheDocument()
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("兼具教師與學員角色時顯示教師視角", async () => {
    // 他自己的已通過課程在 ET04「我的課程」看得到；兩張表塞同一頁只會讓畫面變長。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByLabelText("學員姓名")).toBeInTheDocument()
  })
})
