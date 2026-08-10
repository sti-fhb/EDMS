import { screen } from "@testing-library/react"
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

  it("無新增角色入口（角色為固定 enum）", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.queryByRole("button", { name: /新增角色/ })).not.toBeInTheDocument()
  })
})