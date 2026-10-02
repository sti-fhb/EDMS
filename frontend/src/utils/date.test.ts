// @vitest-environment node
// 純邏輯測試：不碰 DOM，**也不經 app 的 axios 發請求**——跳過 jsdom 省下建置環境的
// 開銷（#376）。⚠️ 日後若在本檔加入會發送請求的測試，請把這兩行拿掉：`http` 的
// baseURL 是相對路徑 `/api`，node 環境沒有 document origin，axios 會改走 http
// adapter 並以 `TypeError: Invalid URL` 失敗。
import { afterEach, describe, expect, it, vi } from "vitest"

import { formatDateTimeTaipei, fromDateTimeLocalInput, toDateTimeLocalInput, todayTaipei } from "./date"

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

describe("formatDateTimeTaipei（稽核導向畫面）", () => {
  it("不論執行環境時區，一律呈現台灣時間", () => {
    // UTC 仍是 09/30、台灣已跨到 10/01。瀏覽器時區走 formatDateTime 時這裡會因機器而異，
    // 稽核畫面必須與後端的台灣時間日界一致（#483）。
    expect(formatDateTimeTaipei("2026-09-30T23:30:00Z")).toBe("2026/10/01 07:30")
  })

  it("台灣日界兩側", () => {
    expect(formatDateTimeTaipei("2026-09-30T15:59:00Z")).toBe("2026/09/30 23:59")
    expect(formatDateTimeTaipei("2026-09-30T16:00:00Z")).toBe("2026/10/01 00:00") // 非 24:00
  })

  it("與 formatDateTime 的格式一致（YYYY/MM/DD HH:mm）", () => {
    expect(formatDateTimeTaipei("2026-10-01T04:05:00Z")).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/)
  })

  it("空值與非法值回安全預設", () => {
    expect(formatDateTimeTaipei(null)).toBe("—")
    expect(formatDateTimeTaipei("")).toBe("—")
    expect(formatDateTimeTaipei("not-a-date")).toBe("—")
  })
})

describe("todayTaipei（日期選擇器上限）", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  const at = (iso: string): string => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(iso))
    return todayTaipei()
  }

  it("UTC 仍是前一天、台灣已跨日時回台灣的日期", () => {
    // 原本的寫法 `new Date().toISOString().slice(0, 10)` 在此時點回 2026-09-30，
    // 使日期選擇器的 max 停在昨天——台灣時間早上 8 點前選不到今天（#483 第 2 項）。
    expect(at("2026-09-30T23:30:00Z")).toBe("2026-10-01")
  })

  it("台灣當日稍晚仍是同一天", () => {
    expect(at("2026-10-01T15:30:00Z")).toBe("2026-10-01")
  })

  it("台灣日界剛過的瞬間即換日", () => {
    expect(at("2026-10-01T15:59:59Z")).toBe("2026-10-01") // 台灣 23:59:59
    expect(at("2026-10-01T16:00:00Z")).toBe("2026-10-02") // 台灣 00:00:00
  })

  it("格式為 YYYY-MM-DD（<input type=\"date\"> 可直接吃）", () => {
    expect(at("2026-02-03T04:05:06Z")).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
