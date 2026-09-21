import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { RequireRetestDialog } from "./RequireRetestDialog"
import { renderWithProviders } from "../../test/renderWithProviders"

function setup(passedCount = 3) {
  const onCancel = vi.fn()
  const onDecide = vi.fn()
  renderWithProviders(
    <RequireRetestDialog open passedCount={passedCount} onCancel={onCancel} onDecide={onDecide} />,
  )
  return { onCancel, onDecide }
}

describe("RequireRetestDialog", () => {
  it("寫出受影響人數——教師要據此判斷這個決定的份量", () => {
    setup(12)
    // 「要求 1 個人重考」與「要求 12 個人重考」是完全不同的決定。
    // 用 dialog 的整體文字斷言：人數在文案中出現兩次，getByText 會因多重命中而拋錯。
    expect(screen.getByRole("dialog")).toHaveTextContent("12 位學員已通過")
  })

  it("三顆按鈕各自對應一種結果", () => {
    setup()
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "僅儲存，不要求重測" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "儲存並要求重測" })).toBeInTheDocument()
  })

  it("選「儲存並要求重測」回報 true", async () => {
    const { onDecide, onCancel } = setup()
    await userEvent.click(screen.getByRole("button", { name: "儲存並要求重測" }))
    expect(onDecide).toHaveBeenCalledWith(true)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it("選「僅儲存」回報 false——仍會儲存，只是不要求重測", async () => {
    const { onDecide } = setup()
    await userEvent.click(screen.getByRole("button", { name: "僅儲存，不要求重測" }))
    expect(onDecide).toHaveBeenCalledWith(false)
  })

  it("取消不做任何儲存", async () => {
    const { onDecide, onCancel } = setup()
    await userEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onDecide).not.toHaveBeenCalled()
  })

  it("按 ESC 等同取消，不會靜默儲存", async () => {
    // 🔴 這是本元件存在的理由。共用的 `confirm` 只有兩顆鈕，且 Dialog 的 onClose
    // 綁在 onCancel 上——若把「取消」對應到「不要求但仍儲存」，一個誤按 ESC 就會
    // 靜默儲存，而本功能的裁示重點正是「系統不猜意圖」。
    const { onDecide, onCancel } = setup()
    await userEvent.keyboard("{Escape}")
    expect(onCancel).toHaveBeenCalled()
    expect(onDecide).not.toHaveBeenCalled()
  })

  it("說明兩種選擇都不會刪除作答紀錄", () => {
    // US6 AC 12 / US9 AC 6：教師最可能誤解的就是這一點，要寫在他做決定的當下。
    setup()
    expect(screen.getByText(/不會刪除任何作答紀錄/)).toBeInTheDocument()
  })
})
