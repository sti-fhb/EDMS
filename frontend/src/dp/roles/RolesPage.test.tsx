import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { RolesPage } from "./RolesPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

describe("RolesPage 權限管理", () => {
  it("顯示可管理模組頁籤（DM）+ 使用者列與 DM 角色核取（現況勾選）", async () => {
    renderWithProviders(<RolesPage />)
    expect(await screen.findByText("文件管理（DM）")).toBeInTheDocument()
    expect(await screen.findByText("王曉明")).toBeInTheDocument()
    // DM 四角色欄；u1 現況為編輯者 → 編輯者勾選、管理者未勾選
    expect(screen.getByRole("checkbox", { name: "王曉明 編輯者" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "王曉明 管理者" })).not.toBeChecked()
  })

  it("勾選角色 → 呼叫指派並顯示即時生效提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const adminBox = await screen.findByRole("checkbox", { name: "王曉明 管理者" })
    await user.click(adminBox)
    expect(await screen.findByText("角色 / 標籤已更新並即時生效")).toBeInTheDocument()
  })

  it("自我保護：模組回 403 → 顯示錯誤訊息", async () => {
    server.use(
      http.put("/api/dp/roles/:module/assignments/:userId", () =>
        HttpResponse.json({ error_code: "DP_ROLE_002", error_message: "無法取消自己的管理者角色" }, { status: 403 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const box = await screen.findByRole("checkbox", { name: "王曉明 編輯者" })
    await user.click(box)
    expect(await screen.findByText("無法取消自己的管理者角色")).toBeInTheDocument()
  })

  it("無可管理模組 → 顯示提示、不顯示頁籤", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json([])))
    renderWithProviders(<RolesPage />)
    expect(await screen.findByText("您目前無可管理的模組權限。")).toBeInTheDocument()
    expect(screen.queryByText("文件管理（DM）")).not.toBeInTheDocument()
  })

  it("帳號欄顯示 email、最後異動顯示操作者姓名（非原始 ID）", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.getByText("ming@example.com")).toBeInTheDocument() // 帳號欄＝email
    expect(screen.getByText(/系統管理員/)).toBeInTheDocument() // 最後異動＝姓名（非 "admin"）
    expect(screen.queryByText(/^admin｜/)).not.toBeInTheDocument()
  })

  it("停用帳號：列標示「已停用」、未持有的角色不可勾選（#250 AC1）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("林離職")).closest("tr")!
    expect(within(row).getByText("已停用")).toBeInTheDocument()
    // u2 未持有任何角色 → 四個核取皆為「新增」方向，一律禁用
    expect(within(row).getByRole("checkbox", { name: "林離職 編輯者" })).toBeDisabled()
    expect(within(row).getByRole("checkbox", { name: "林離職 管理者" })).toBeDisabled()
  })

  it("鎖定中帳號：列標示「已鎖定」、未持有的角色不可勾選（#250 AC2）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("陳鎖定")).closest("tr")!
    expect(within(row).getByText("已鎖定")).toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "陳鎖定 編輯者" })).toBeDisabled()
  })

  it("停用 / 鎖定帳號仍可撤除既有權限（Security Review MEDIUM-3：保留離職降權路徑）", async () => {
    renderWithProviders(<RolesPage />)
    // u3 陳鎖定持有閱覽者 → 該核取為「撤除」方向，須可操作
    const row = (await screen.findByText("陳鎖定")).closest("tr")!
    const held = within(row).getByRole("checkbox", { name: "陳鎖定 閱覽者" })
    expect(held).toBeChecked()
    expect(held).toBeEnabled()
    // 可見對象編輯鈕保持可用（dialog 內只允許取消已選項）
    expect(within(row).getByRole("button", { name: "編輯" })).toBeEnabled()
  })

  it("撤除停用帳號之角色 → 送出並顯示成功（不被前端擋下）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("陳鎖定")).closest("tr")!
    await user.click(within(row).getByRole("checkbox", { name: "陳鎖定 閱覽者" }))
    expect(await screen.findByText("角色 / 標籤已更新並即時生效")).toBeInTheDocument()
  })

  it("正常帳號不受影響：無狀態標籤、可操作（#250 迴歸）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("王曉明")).closest("tr")!
    expect(within(row).queryByText("已停用")).not.toBeInTheDocument()
    expect(within(row).queryByText("已鎖定")).not.toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "王曉明 編輯者" })).toBeEnabled()
    expect(within(row).getByRole("button", { name: "編輯" })).toBeEnabled()
  })

  it("鎖定已逾時的帳號視為正常（不可誤以 locked_until 非空判定）", async () => {
    server.use(
      http.get("/api/dp/roles/:module/assignments", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "u9",
              user_name: "已解鎖",
              email: "unlocked@example.com",
              status: "ACTIVE",
              locked_until: "2020-01-01T00:00:00Z", // 早已逾時 → 自動解鎖
              roles: [],
              groups: [],
              last_modified_by: null,
              last_modified_by_name: null,
              last_modified_date: null,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("已解鎖")).closest("tr")!
    expect(within(row).queryByText("已鎖定")).not.toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "已解鎖 編輯者" })).toBeEnabled()
  })

  it("無新增角色入口（角色為固定 enum）", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.queryByRole("button", { name: /新增角色/ })).not.toBeInTheDocument()
  })
})