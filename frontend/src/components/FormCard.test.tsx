import TextField from "@mui/material/TextField"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { FormCard } from "./FormCard"
import { renderWithProviders } from "../test/renderWithProviders"

describe("FormCard", () => {
  it("送出表單觸發 onSave、取消觸發 onCancel", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    const onCancel = vi.fn()
    renderWithProviders(
      <FormCard title="建立帳號" onSave={onSave} onCancel={onCancel}>
        <TextField label="姓名" />
      </FormCard>,
    )

    expect(screen.getByRole("heading", { name: "建立帳號" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "儲存" }))
    expect(onSave).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole("button", { name: "取消" }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("saving 時停用儲存與取消按鈕", () => {
    renderWithProviders(
      <FormCard title="建立帳號" onSave={() => {}} onCancel={() => {}} saving>
        <TextField label="姓名" />
      </FormCard>,
    )

    expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled()
  })
})
