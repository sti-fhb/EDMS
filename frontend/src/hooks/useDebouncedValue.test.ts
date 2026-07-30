import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useDebouncedValue } from "./useDebouncedValue"

describe("useDebouncedValue", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("延遲未到前維持舊值，到期後才更新為最新值", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "a" },
    })
    expect(result.current).toBe("a")

    rerender({ v: "ab" })
    expect(result.current).toBe("a") // 未到期仍舊值
    act(() => vi.advanceTimersByTime(300))
    expect(result.current).toBe("ab")
  })

  it("快速連續變動只採用最後一次（前一個 timer 被 clear）", () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "a" },
    })

    rerender({ v: "ab" })
    act(() => vi.advanceTimersByTime(200)) // 距 "ab" 200ms，未到期
    rerender({ v: "abc" }) // 又變動，"ab" 的 timer 應被 clear
    act(() => vi.advanceTimersByTime(200)) // 距 "abc" 僅 200ms
    expect(result.current).toBe("a") // 仍未更新（中途的 "ab" 未被採用）
    act(() => vi.advanceTimersByTime(100)) // 補足到 "abc" 的 300ms
    expect(result.current).toBe("abc")
  })
})
