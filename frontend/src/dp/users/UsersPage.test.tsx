import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { UsersPage } from "./UsersPage"
import { server } from "../../test/server"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("UsersPage 使用者操作流程", () => {
  it("載入清單並依狀態顯示三態與對應操作", async () => {
    renderWithProviders(<UsersPage />)

    expect(await screen.findByText("陳大華")).toBeInTheDocument()
    expect(screen.getByText("啟用中")).toBeInTheDocument()
    expect(screen.getByText("已鎖定")).toBeInTheDocument()
    expect(screen.getByText("已停用")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "停用" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "解鎖" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "啟用" })).toBeInTheDocument()
  })

  it("建立帳號＝寄邀請：填 Email/姓名（無密碼欄）送出後顯示邀請已寄", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getByRole("button", { name: /建立帳號/ }))
    // 建立表單無「初始密碼」欄位（#67）
    expect(screen.queryByLabelText(/密碼/)).not.toBeInTheDocument()
    await user.type(screen.getByLabelText("帳號（Email）"), "new@edms.local")
    await user.type(screen.getByLabelText("姓名"), "新人")
    await user.click(screen.getByRole("button", { name: "寄送邀請" }))

    expect(await screen.findByText(/邀請信已寄出/)).toBeInTheDocument()
  })

  it("建立帳號：Email 格式錯誤時顯示欄位錯誤、不送出", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getByRole("button", { name: /建立帳號/ }))
    await user.type(screen.getByLabelText("帳號（Email）"), "bad-email")
    await user.type(screen.getByLabelText("姓名"), "新人")
    await user.click(screen.getByRole("button", { name: "寄送邀請" }))

    expect(await screen.findByText("Email 格式不正確")).toBeInTheDocument()
  })

  it("Email 重複時顯示後端錯誤訊息", async () => {
    const user = userEvent.setup()
    server.use(
      http.post("/api/dp/users", () =>
        HttpResponse.json({ error_code: "DP_USER_007", error_message: "此 Email 已被使用" }, { status: 409 }),
      ),
    )
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getByRole("button", { name: /建立帳號/ }))
    await user.type(screen.getByLabelText("帳號（Email）"), "dup@edms.local")
    await user.type(screen.getByLabelText("姓名"), "重複")
    await user.click(screen.getByRole("button", { name: "寄送邀請" }))

    expect(await screen.findByText("此 Email 已被使用")).toBeInTheDocument()
  })

  it("停用：二次確認後送出並提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getByRole("button", { name: "停用" }))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/兩端將同步失效/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "確定停用" }))

    expect(await screen.findByText("帳號已停用")).toBeInTheDocument()
  })

  it("解鎖：對已鎖定帳號送出並提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("林小美")

    await user.click(screen.getByRole("button", { name: "解鎖" }))
    expect(await screen.findByText("帳號已解鎖")).toBeInTheDocument()
  })

  it("啟用：對已停用帳號送出並提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("張志豪")

    await user.click(screen.getByRole("button", { name: "啟用" }))
    expect(await screen.findByText("帳號已啟用")).toBeInTheDocument()
  })

  it("編輯：Email 唯讀不可改、無密碼欄，改姓名後提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getAllByRole("button", { name: "編輯" })[0])
    const emailInput = await screen.findByLabelText("帳號（Email）")
    expect(emailInput).toHaveValue("active@edms.local")
    expect(emailInput).toBeDisabled() // Email 唯讀（#67）
    expect(screen.queryByLabelText(/密碼/)).not.toBeInTheDocument()

    await user.clear(screen.getByLabelText("姓名"))
    await user.type(screen.getByLabelText("姓名"), "陳大華改")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText(/已更新姓名/)).toBeInTheDocument()
  })

  // ---- 待啟用邀請頁籤（#67）----

  it("切到待啟用邀請頁籤：顯示邀請列與有效中 / 已逾期狀態", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")

    await user.click(screen.getByRole("tab", { name: /待啟用邀請/ }))

    expect(await screen.findByText("周雅婷")).toBeInTheDocument()
    expect(screen.getByText("李國豪")).toBeInTheDocument()
    expect(screen.getByText("有效中")).toBeInTheDocument()
    expect(screen.getByText("已逾期")).toBeInTheDocument()
  })

  it("待啟用邀請：重寄邀請提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")
    await user.click(screen.getByRole("tab", { name: /待啟用邀請/ }))
    await screen.findByText("周雅婷")

    await user.click(screen.getAllByRole("button", { name: "重寄邀請" })[0])
    expect(await screen.findByText("邀請信已重寄")).toBeInTheDocument()
  })

  it("待啟用邀請：取消邀請二次確認後提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)
    await screen.findByText("陳大華")
    await user.click(screen.getByRole("tab", { name: /待啟用邀請/ }))
    await screen.findByText("周雅婷")

    await user.click(screen.getAllByRole("button", { name: "取消邀請" })[0])
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "確定取消" }))

    expect(await screen.findByText("已取消邀請")).toBeInTheDocument()
  })
})