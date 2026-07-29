import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { TemplatesPage } from "./TemplatesPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

async function gotoEtTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("tab", { name: "教育訓練（ET）" }))
}

describe("TemplatesPage 通知範本維護（條列 + 編輯展開）", () => {
  it("依 MODULE 分頁條列；DP 系統信之停用鈕禁用（不可停用；系統信身分由分頁標示、列上不重複標記）", async () => {
    renderWithProviders(<TemplatesPage />)
    // DP 頁籤預設：見系統信 PWD_RESET
    expect(await screen.findByText("PWD_RESET")).toBeInTheDocument()
    // 列上不再重複「系統信」標記（已在「系統信（共用）」分頁下）
    expect(screen.queryByText("系統信")).not.toBeInTheDocument()
    // 系統信「停用」鈕禁用
    expect(screen.getByRole("button", { name: "停用" })).toBeDisabled()
  })

  it("點編輯 → 展開表單改主旨儲存 → 成功提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await gotoEtTab(user)
    await user.click(await screen.findByRole("button", { name: "編輯" }))

    const subject = await screen.findByLabelText("主旨")
    await user.clear(subject)
    await user.type(subject, "課程邀請（改）")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("範本已更新")).toBeInTheDocument()
  })

  it("編輯空主旨 → 前端 Zod 擋下、不送出", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await gotoEtTab(user)
    await user.click(await screen.findByRole("button", { name: "編輯" }))
    await user.clear(await screen.findByLabelText("主旨"))
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("請輸入主旨")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("範本已更新")).not.toBeInTheDocument())
  })

  it("編輯儲存遇版本衝突（409 DP_MAIL_004）→ 顯示錯誤訊息", async () => {
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
    await gotoEtTab(user)
    await user.click(await screen.findByRole("button", { name: "編輯" }))
    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(await screen.findByText("內容已被他人修改，請重新載入後再儲存")).toBeInTheDocument()
  })

  it("行內停用非系統信範本 → 即時儲存成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await gotoEtTab(user)
    // ET COURSE_INVITE 啟用中 → 停用鈕可點
    await user.click(await screen.findByRole("button", { name: "停用" }))
    expect(await screen.findByText("範本已更新")).toBeInTheDocument()
  })

  it("行內改管道 → 即時儲存成功", async () => {
    const user = userEvent.setup()
    renderWithProviders(<TemplatesPage />)
    await gotoEtTab(user)
    // 管道下拉（MUI Select 以 combobox 呈現）改為「系統內部+email」
    const select = await screen.findByRole("combobox")
    await user.click(select)
    await user.click(await screen.findByRole("option", { name: "系統內部+email" }))
    expect(await screen.findByText("範本已更新")).toBeInTheDocument()
  })
})
