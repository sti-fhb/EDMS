import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ProfilePage } from "./ProfilePage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

describe("ProfilePage 個人資料維護", () => {
  it("提供返回主頁按鈕", async () => {
    renderWithProviders(<ProfilePage />)
    expect(await screen.findByRole("button", { name: /返回主頁/ })).toBeInTheDocument()
  })

  it("載入後帶入現值，姓名可更新並提示成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ProfilePage />)

    const nameInput = await screen.findByDisplayValue("測試員")
    await user.clear(nameInput)
    await user.type(nameInput, "新名字")
    await user.click(screen.getByRole("button", { name: "儲存姓名" }))

    expect(await screen.findByText("姓名已更新")).toBeInTheDocument()
  })

  it("目前帳號唯讀、送出新 Email 後提示驗證信已寄", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ProfilePage />)

    expect(await screen.findByDisplayValue("me@example.com")).toBeDisabled()
    await user.type(screen.getByLabelText("變更為新 Email"), "new@example.com")
    await user.click(screen.getByRole("button", { name: "寄驗證信" }))

    expect(await screen.findByText(/驗證信已寄至新 Email/)).toBeInTheDocument()
    // 成功後寄信按鈕進入冷卻：disable + 顯示倒數（#74，回應帶 retry_after）
    await waitFor(() => expect(screen.getByRole("button", { name: /寄驗證信（.+ 後）/ })).toBeDisabled())
  })

  it("新 Email 已被使用 → 顯示後端錯誤（PROFILE-006）", async () => {
    server.use(
      http.put("/api/dp/user/me/email", () =>
        HttpResponse.json({ error_code: "DP_USER_007", error_message: "此 Email 已被使用" }, { status: 409 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<ProfilePage />)
    const emailInput = await screen.findByLabelText("變更為新 Email")
    await user.type(emailInput, "taken@example.com")
    await user.click(screen.getByRole("button", { name: "寄驗證信" }))

    expect(await screen.findByText("此 Email 已被使用")).toBeInTheDocument()
    // 已被使用 → 欄位清空（該值已知不可用）
    await waitFor(() => expect(emailInput).toHaveValue(""))
  })

  it("待驗證變更中 → 顯示審核中橫幅", async () => {
    server.use(
      http.get("/api/dp/user/me", () =>
        HttpResponse.json({
          user_id: "u1",
          email: "me@example.com",
          user_name: "測試員",
          pending_email: "pending@example.com",
        }),
      ),
    )
    renderWithProviders(<ProfilePage />)
    expect(await screen.findByText(/變更審核中：pending@example.com/)).toBeInTheDocument()
  })

  it("變更密碼對話框：填舊 / 新 / 確認送出 → 成功提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByRole("button", { name: "變更密碼" }))
    await user.type(screen.getByLabelText("舊密碼"), "Abcd1234")
    await user.type(screen.getByLabelText("新密碼"), "Xyz98765!")
    await user.type(screen.getByLabelText("確認新密碼"), "Xyz98765!")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("密碼已更新")).toBeInTheDocument()
  })

  it("變更密碼：兩次不一致 → 前端擋下顯示錯誤", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ProfilePage />)

    await user.click(await screen.findByRole("button", { name: "變更密碼" }))
    await user.type(screen.getByLabelText("舊密碼"), "Abcd1234")
    await user.type(screen.getByLabelText("新密碼"), "Xyz98765!")
    await user.type(screen.getByLabelText("確認新密碼"), "Diff9999!")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("兩次輸入之新密碼不一致")).toBeInTheDocument()
    // 未送出成功
    await waitFor(() => expect(screen.queryByText("密碼已更新")).not.toBeInTheDocument())
  })
})
