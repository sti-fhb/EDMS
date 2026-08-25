import { describe, expect, it } from "vitest"

import { fromDateTimeLocalInput, toDateTimeLocalInput } from "./date"

describe("datetime-local 與 ISO 8601 轉換", () => {
  it("往返後回到原本的本地牆上時間", () => {
    const local = "2026-04-15T09:00"
    expect(toDateTimeLocalInput(fromDateTimeLocalInput(local))).toBe(local)
  })

  it("送出值為帶 Z 的 ISO 8601（非原樣 naive 字串）", () => {
    const iso = fromDateTimeLocalInput("2026-04-15T09:00")
    expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    expect(iso).not.toBe("2026-04-15T09:00")
  })

  it("顯示時做真正的時區換算，而非截斷字串", () => {
    // 直接截斷（iso.slice(0,16)）會得到 UTC 的 01:00；正確結果須為該時刻的本地時間
    const iso = "2026-04-15T01:00:00.000Z"
    const expected = new Date(iso)
    const shown = toDateTimeLocalInput(iso)
    expect(shown.slice(11, 13)).toBe(String(expected.getHours()).padStart(2, "0"))
  })

  it("空值與非法值回安全預設", () => {
    expect(toDateTimeLocalInput(null)).toBe("")
    expect(toDateTimeLocalInput("not-a-date")).toBe("")
    expect(fromDateTimeLocalInput("")).toBeNull()
    expect(fromDateTimeLocalInput("not-a-date")).toBeNull()
  })
})
