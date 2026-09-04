import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { RolesPage } from "../dp/roles/RolesPage"
import { NAV_GROUPS } from "../layouts/navItems"
import { renderWithProviders } from "../test/renderWithProviders"
import { server } from "../test/server"
import { Sidebar } from "./Sidebar"

describe("Sidebar", () => {
  it("具模組管理者身分時渲染「系統管理者後台」群組與其六個導覽項目", async () => {
    renderWithProviders(<Sidebar />)
    const adminGroup = NAV_GROUPS.find((g) => g.title === "系統管理者後台")
    expect(adminGroup).toBeDefined()
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
    expect(adminGroup?.items).toHaveLength(6)
    for (const item of adminGroup?.items ?? []) {
      expect(screen.getByText(item.label)).toBeInTheDocument()
    }
  })

  it("#250：非 ET 且非 DM 管理者時，隱藏「系統管理者後台」整個群組（模組群組仍在）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({
          et: { has_role: true, is_admin: false },
          dm: { has_role: true, is_admin: false },
        }),
      ),
    )
    renderWithProviders(<Sidebar />)
    // 以模組群組確認已渲染完成（後台群組不該出現，不能用它當標記）
    expect(await screen.findByText("文件管理")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("系統管理者後台")).not.toBeInTheDocument())
    expect(screen.queryByText("使用者管理")).not.toBeInTheDocument()
    expect(screen.queryByText("角色 / 權限")).not.toBeInTheDocument()
  })

  it("#250：僅具 ET 管理者（DM 非管理者）時仍顯示「系統管理者後台」（門檻為任一模組）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({
          et: { has_role: true, is_admin: true },
          dm: { has_role: true, is_admin: false },
        }),
      ),
    )
    renderWithProviders(<Sidebar />)
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
  })

  it("#250：非審核者（reviewer-access can_access=false）時隱藏「簽核中心」單項（其餘 DM 項仍在）", async () => {
    server.use(http.get("/api/dm/reviewer-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    expect(await screen.findByText("文件庫")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("簽核中心")).not.toBeInTheDocument())
  })

  it("具 DM 權限（module-summary dm.has_role=true）時顯示「文件管理」群組與其六個 /dm 項目", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    const dmGroup = NAV_GROUPS.find((g) => g.title === "文件管理")
    expect(dmGroup?.items).toHaveLength(6)
    // 個人專區依 access 非同步閘（預設 can_access=true）→ 用 findBy 等其解析
    for (const item of dmGroup?.items ?? []) {
      expect(item.path.startsWith("/dm/")).toBe(true)
      expect(await screen.findByText(item.label)).toBeInTheDocument()
    }
  })

  it("US9：具 DM 角色但非編輯 / 審核者（access can_access=false）時，隱藏「個人專區」單項（其餘 DM 項仍在）", async () => {
    server.use(http.get("/api/dm/personal/access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    expect(await screen.findByText("文件庫")).toBeInTheDocument() // 其餘 DM 項仍顯示
    await waitFor(() => expect(screen.queryByText("個人專區")).not.toBeInTheDocument())
  })

  it("US10/US11/US13：具 DM 角色但非管理者（admin-access can_access=false）時，隱藏所有 admin-only 項（已廢止 / 變更歷程 / 閱讀統計 KPI），其餘 DM 項仍在", async () => {
    server.use(http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    expect(await screen.findByText("文件庫")).toBeInTheDocument() // 其餘 DM 項仍顯示
    await waitFor(() => expect(screen.queryByText("已廢止文件查詢")).not.toBeInTheDocument())
    expect(screen.queryByText("文件變更歷程查詢")).not.toBeInTheDocument()
    expect(screen.queryByText("閱讀統計 KPI")).not.toBeInTheDocument()
  })

  it("兼具教師與學員角色時顯示「教育訓練」群組與其四個 /et 項目", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("教育訓練")).toBeInTheDocument())
    const etGroup = NAV_GROUPS.find((g) => g.title === "教育訓練")
    expect(etGroup?.items).toHaveLength(4)
    for (const item of etGroup?.items ?? []) {
      expect(item.path.startsWith("/et/")).toBe(true)
      // `findBy`：項目要等能力查詢回來才出現（#247 起依角色分流，不再同步渲染）
      expect(await screen.findByText(item.label)).toBeInTheDocument()
    }
  })

  it("純學員只看到「我的課程」，看不到教學管理項（#247）", async () => {
    server.use(
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: false, can_learn: true }),
      ),
    )
    renderWithProviders(<Sidebar />)

    expect(await screen.findByText("我的課程")).toBeInTheDocument()
    // 核可查詢**兩種角色都看得到**，只是內容不同（`ApprovalQueryPage` 之說明：
    // 教師查全部學員、學員查自己已通過的課程）。
    expect(screen.getByText("核可查詢")).toBeInTheDocument()
    // 群組門檻只判「有無任一 ET 角色」——不夠。純學員看到「課程列表 / 學員」等於
    // 看到點進去只會 403 的項目。
    await waitFor(() => expect(screen.queryByText("課程列表")).not.toBeInTheDocument())
    expect(screen.queryByText("學員")).not.toBeInTheDocument()
  })

  it("學員角色被停用者看不到「我的課程」（#247）", async () => {
    server.use(
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: true, can_manage_courses: true, can_learn: false }),
      ),
    )
    renderWithProviders(<Sidebar />)

    // 學員角色雖於建立帳號時自動授予，但管理者可停用個別指派。
    expect(await screen.findByText("課程列表")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("我的課程")).not.toBeInTheDocument())
  })

  it("無 ET 權限（et.has_role=false）時不顯示「教育訓練」群組（最小知悉）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        // is_admin 保持 true：本案驗的是 ET 群組門檻，後台群組須維持顯示以當渲染完成標記
        HttpResponse.json({
          et: { has_role: false, is_admin: false },
          dm: { has_role: true, is_admin: true },
        }),
      ),
    )
    renderWithProviders(<Sidebar />)
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("教育訓練")).not.toBeInTheDocument())
    expect(screen.queryByText("課程列表")).not.toBeInTheDocument()
  })

  it("無 DM 權限（dm.has_role=false）時不顯示「文件管理」群組（DP 群組仍在）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        // 同上：驗 DM 群組門檻，後台群組維持顯示
        HttpResponse.json({
          et: { has_role: true, is_admin: true },
          dm: { has_role: false, is_admin: false },
        }),
      ),
    )
    renderWithProviders(<Sidebar />)
    // DP 群組恆顯示，確認已渲染完成
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()
    // 等 module-summary 解析後，DM 群組與其項目皆不應出現
    await waitFor(() => expect(screen.queryByText("文件管理")).not.toBeInTheDocument())
    expect(screen.queryByText("文件庫")).not.toBeInTheDocument()
  })

  it("#250 AC11：角色異動後側欄即時更新，不需重登", async () => {
    // 模擬「管理者把自己的 DM 管理者角色移除」：assign 成功後 module-summary 改回非管理者
    let dmIsAdmin = true
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({
          et: { has_role: true, is_admin: false },
          dm: { has_role: true, is_admin: dmIsAdmin },
        }),
      ),
      http.put("/api/dp/roles/:module/assignments/:userId", () => {
        dmIsAdmin = false
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    // 兩個元件共用同一個 QueryClient，才驗得到 RolesPage 的 invalidate 傳導到 Sidebar
    renderWithProviders(
      <>
        <Sidebar />
        <RolesPage />
      </>,
    )
    expect(await screen.findByText("系統管理者後台")).toBeInTheDocument()

    await user.click(await screen.findByRole("checkbox", { name: "王曉明 管理者" }))

    // 不重整、不重登，側欄自行收起後台群組（RolesPage 於 onSuccess invalidate moduleSummary）
    await waitFor(() => expect(screen.queryByText("系統管理者後台")).not.toBeInTheDocument())
    expect(screen.queryByText("使用者管理")).not.toBeInTheDocument()
  })

  it("群組由上而下的順序為：教育訓練 → 文件管理 → 系統管理者後台", async () => {
    renderWithProviders(<Sidebar />)
    await screen.findByText("系統管理者後台")
    const nav = screen.getByRole("navigation", { name: "主導覽" })
    const titles = Array.from(nav.querySelectorAll("span")).map((el) => el.textContent)
    const groupTitles = titles.filter((t) => t && ["教育訓練", "文件管理", "系統管理者後台"].includes(t))
    expect(groupTitles).toEqual(["教育訓練", "文件管理", "系統管理者後台"])
  })

  it("每個顯示中的導覽項目連到對應路由", async () => {
    renderWithProviders(<Sidebar />)
    await waitFor(() => expect(screen.getByText("文件管理")).toBeInTheDocument())
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        expect(await screen.findByRole("link", { name: item.label })).toHaveAttribute("href", item.path)
      }
    }
  })
})