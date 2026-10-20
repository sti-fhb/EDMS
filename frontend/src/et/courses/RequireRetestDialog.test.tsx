import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { RequireRetestDialog } from "./RequireRetestDialog"
import { renderWithProviders } from "../../test/renderWithProviders"

function setup(
  affectedCount = 3,
  extra: { staged?: boolean; closed?: boolean; retestPending?: boolean; cancelsPending?: boolean } = {},
) {
  const onCancel = vi.fn()
  const onDecide = vi.fn()
  renderWithProviders(
    <RequireRetestDialog
      open
      affectedCount={affectedCount}
      onCancel={onCancel}
      onDecide={onDecide}
      {...extra}
    />,
  )
  return { onCancel, onDecide }
}

describe("RequireRetestDialog", () => {
  it("寫出受影響人數——教師要據此判斷這個決定的份量", () => {
    setup(12)
    // 「要求 1 個人重考」與「要求 12 個人重考」是完全不同的決定。
    // 用 dialog 的整體文字斷言：人數在文案中出現兩次，getByText 會因多重命中而拋錯。
    expect(screen.getByRole("dialog")).toHaveTextContent("12 位學員已作答")
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

  it("說明對象不限已通過者、且最高分只計重測後（#709）", () => {
    setup()
    expect(screen.getByRole("dialog")).toHaveTextContent("不論是否已通過")
    expect(screen.getByRole("dialog")).toHaveTextContent("最高分只計重測後的作答")
  })

  it("說明兩種選擇都不會刪除作答紀錄", () => {
    // US6 AC 12 / US9 AC 6：教師最可能誤解的就是這一點，要寫在他做決定的當下。
    setup()
    expect(screen.getByText(/不會刪除任何作答紀錄/)).toBeInTheDocument()
  })

  describe("已發布課程（編輯進暫存區，#631）", () => {
    it("寫明重測要等按「更新」才發生", () => {
      // 🔴 2026-10-17 裁示把重測延到「更新」當下。文案不跟著改的話，教師在這裡按下
      // 「儲存並要求重測」會以為信已經寄出去了。
      setup(3, { staged: true })
      expect(screen.getByRole("dialog")).toHaveTextContent(/不會立刻執行/)
      expect(screen.getByRole("dialog")).toHaveTextContent(/按下「更新」/)
    })

    it("草稿不提生效時點——那裡本來就是即時的", () => {
      // 🔴 反向探針。少了它，把那段文案寫成無條件顯示也會讓上一條通過，
      // 而草稿課程根本沒有「更新」這顆按鈕，教師會去找一顆不存在的東西。
      setup(3, { staged: false })
      expect(screen.getByRole("dialog")).not.toHaveTextContent(/不會立刻執行/)
    })

    it("已有待生效的重測要求時，說明「僅儲存」會把它取消", () => {
      // 🔴 不講這件事，「僅儲存，不要求重測」就是一顆會靜默撤銷十分鐘前決定的按鈕。
      setup(3, { staged: true, retestPending: true, cancelsPending: true })
      expect(screen.getByRole("dialog")).toHaveTextContent(/已有一筆待生效的重測要求/)
      expect(screen.getByRole("dialog")).toHaveTextContent(/會把它一併取消/)
    })

    it("改題／刪題路徑：說明「僅儲存」不會取消，要到測驗設定取消（#767 A1）", () => {
      // 後端只有測驗設定那一支會清旗標（quiz/service.py），改題刪題的「僅儲存」是
      // 「這次不另外要求」——原文宣稱會取消，教師據此以為撤銷了，按更新後全班照樣被退回。
      setup(3, { staged: true, retestPending: true, cancelsPending: false })
      expect(screen.getByRole("dialog")).toHaveTextContent(/已有一筆待生效的重測要求/)
      expect(screen.getByRole("dialog")).toHaveTextContent(/不會取消它/)
      expect(screen.getByRole("dialog")).toHaveTextContent(/測驗設定/)
      expect(screen.getByRole("dialog")).not.toHaveTextContent(/會把它一併取消/)
    })

    it("沒有待生效要求時不提——否則每次都在講一件沒發生的事", () => {
      setup(3, { staged: true, retestPending: false })
      expect(screen.getByRole("dialog")).not.toHaveTextContent(/已有一筆待生效的重測要求/)
    })
  })
})

describe("已關閉課程的生效時點說明（#768 第 7 項）", () => {
  // 已關閉課程沒有「更新」鈕，生效要按「更新並重開課」——寫「更新」會叫教師去找一顆不存在的按鈕
  it("已關閉：說明按「更新並重開課」才生效", () => {
    setup(3, { staged: true, closed: true })
    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveTextContent("更新並重開課")
    expect(dialog).not.toHaveTextContent("按下「更新」")
  })

  it("已發布：照舊說明按「更新」（正向錨點）", () => {
    setup(3, { staged: true, closed: false })
    expect(screen.getByRole("dialog")).toHaveTextContent("按下「更新」")
  })
})
