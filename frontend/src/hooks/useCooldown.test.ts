import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useCooldown } from "./useCooldown"

// 倒數依賴 setInterval，用 fake timers 決定性驗證每秒遞減，不等真實時間。
describe("useCooldown", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("start 設定剩餘秒，每秒遞減至 0 後結束", () => {
    const { result } = renderHook(() => useCooldown())
    expect(result.current.active).toBe(false)

    act(() => result.current.start(3))
    expect(result.current.remaining).toBe(3)
    expect(result.current.active).toBe(true)

    act(() => vi.advanceTimersByTime(1000))
    expect(result.current.remaining).toBe(2)

    act(() => vi.advanceTimersByTime(2000))
    expect(result.current.remaining).toBe(0)
    expect(result.current.active).toBe(false)
  })

  it("start(0) 不啟動倒數", () => {
    const { result } = renderHook(() => useCooldown())
    act(() => result.current.start(0))
    expect(result.current.active).toBe(false)
    expect(result.current.remaining).toBe(0)
  })

  it("倒數中再次 start 會重設剩餘秒（重寄後重新計時）", () => {
    const { result } = renderHook(() => useCooldown())
    act(() => result.current.start(2))
    act(() => vi.advanceTimersByTime(1000))
    expect(result.current.remaining).toBe(1)

    act(() => result.current.start(5))
    expect(result.current.remaining).toBe(5)
    expect(result.current.active).toBe(true)
  })
})
