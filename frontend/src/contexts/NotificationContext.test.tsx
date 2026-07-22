import Button from "@mui/material/Button"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { useNotification } from "./NotificationContext"
import { renderWithProviders } from "../test/renderWithProviders"

function Harness({ onOk }: { onOk?: () => void | Promise<void> }) {
  const { message, confirm } = useNotification()
  return (
    <>
      <Button onClick={() => message.success("操作成功")}>觸發成功</Button>
      <Button
        onClick={() =>
          confirm({ title: "確定停用", content: "停用後兩端同步失效", danger: true, onOk: onOk ?? (() => {}) })
        }
      >
        觸發確認
      </Button>
    </>
  )
}

describe("NotificationContext", () => {
  it("message.success 顯示提示文字", async () => {
    const user = userEvent.setup()
    renderWithProviders(<Harness />)

    await user.click(screen.getByRole("button", { name: "觸發成功" }))

    expect(await screen.findByText("操作成功")).toBeInTheDocument()
  })

  it("confirm 顯示對話框，按確認觸發 onOk 並關閉", async () => {
    const user = userEvent.setup()
    const onOk = vi.fn()
    renderWithProviders(<Harness onOk={onOk} />)

    await user.click(screen.getByRole("button", { name: "觸發確認" }))
    expect(await screen.findByText("確定停用")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "確認" }))

    await waitFor(() => expect(onOk).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByText("確定停用")).not.toBeInTheDocument())
  })

  it("confirm 按取消不觸發 onOk", async () => {
    const user = userEvent.setup()
    const onOk = vi.fn()
    renderWithProviders(<Harness onOk={onOk} />)

    await user.click(screen.getByRole("button", { name: "觸發確認" }))
    await user.click(await screen.findByRole("button", { name: "取消" }))

    expect(onOk).not.toHaveBeenCalled()
  })
})
