import { act, renderHook } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { useCrudForm } from "./useCrudForm"

interface Rec {
  id: string
  name: string
}

describe("useCrudForm", () => {
  it("openCreate 顯示表單且 editingRecord 為 null", () => {
    const { result } = renderHook(() => useCrudForm<Rec>())

    expect(result.current.formVisible).toBe(false)
    act(() => result.current.openCreate())

    expect(result.current.formVisible).toBe(true)
    expect(result.current.editingRecord).toBeNull()
  })

  it("openEdit 帶入 editingRecord", () => {
    const { result } = renderHook(() => useCrudForm<Rec>())

    act(() => result.current.openEdit({ id: "1", name: "陳大華" }))

    expect(result.current.formVisible).toBe(true)
    expect(result.current.editingRecord).toEqual({ id: "1", name: "陳大華" })
  })

  it("closeForm 清空狀態並呼叫 onClose", () => {
    const onClose = vi.fn()
    const { result } = renderHook(() => useCrudForm<Rec>({ onClose }))

    act(() => result.current.openEdit({ id: "1", name: "王曉明" }))
    act(() => result.current.closeForm())

    expect(result.current.formVisible).toBe(false)
    expect(result.current.editingRecord).toBeNull()
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
