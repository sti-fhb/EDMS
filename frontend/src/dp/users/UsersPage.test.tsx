import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { UsersPage } from "./UsersPage"
import { renderWithProviders } from "../../test/renderWithProviders"

describe("UsersPage（PR1 骨架）", () => {
  it("渲染標題、篩選列、表格欄位與建立帳號按鈕", () => {
    renderWithProviders(<UsersPage />)

    expect(screen.getByRole("heading", { name: "使用者管理" })).toBeInTheDocument()
    expect(screen.getByLabelText("關鍵字（姓名 / Email）")).toBeInTheDocument()
    expect(screen.getByLabelText("帳號狀態")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /建立帳號/ })).toBeInTheDocument()
    expect(screen.getByText("帳號（Email）")).toBeInTheDocument()
  })

  it("點建立帳號開啟表單殼", async () => {
    const user = userEvent.setup()
    renderWithProviders(<UsersPage />)

    await user.click(screen.getByRole("button", { name: /建立帳號/ }))

    expect(await screen.findByRole("heading", { name: "建立帳號" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /建立（PR2 接上）/ })).toBeInTheDocument()
  })
})
