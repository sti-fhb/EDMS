import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { TemplatesPage } from "./TemplatesPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

describe("TemplatesPage 通知範本維護", () => {
  it("載入後依 MODULE 分頁；DP 系統信標記系統信、啟用開關禁用（不可停用）", async () => {
    renderWithProviders(<TemplatesPage />)
    // DP 頁籤預設：見系統信 PWD_RESET + 系統信標記
    expect(await screen.findByText("PWD_RESET")).toBeInTheDocument()
    expect(screen.getByText("系統信")).toBeInTheDocument()
    // 系統信「啟用」開關禁用
    expect(screen.getByLabelText("啟用（系統信不可停用）")).toBeDisabled()
  })

  it("切到 ET 頁籤 → 編輯主旨儲存 → 成功提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await user.click(await screen.findByRole("tab", { name: "教育訓練（ET）" }))

    const subject = await screen.findByLabelText("主旨")
    await user.clear(subject)
    await user.type(subject, "課程邀請（改）")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("範本已更新")).toBeInTheDocument()
  })

  it("版本衝突（409 DP_MAIL_004）→ 顯示錯誤訊息", async () => {
    server.use(
      http.put("/api/dp/notify/templates/:module/:code", () =>
        HttpResponse.json(
          { error_code: "DP_MAIL_004", error_message: "內容已被他人修改，請重新載入後再儲存" },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await user.click(await screen.findByRole("tab", { name: "教育訓練（ET）" }))
    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(await screen.findByText("內容已被他人修改，請重新載入後再儲存")).toBeInTheDocument()
  })

  it("空主旨 → 前端 Zod 擋下、不送出", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await user.click(await screen.findByRole("tab", { name: "教育訓練（ET）" }))
    const subject = await screen.findByLabelText("主旨")
    await user.clear(subject)
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("請輸入主旨")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("範本已更新")).not.toBeInTheDocument())
  })
})