import { describe, expect, it } from "vitest"

import { formatCronSchedule } from "./cron"

describe("cron 運算式 → 人類可讀執行時點", () => {
  it("每日（dow 與 dom 皆為 *）", () => {
    expect(formatCronSchedule("0 8 * * *")).toBe("每日 08:00 UTC")
  })

  it("每週：day-of-week 以**週一為 0**，與標準 crontab 不同", () => {
    // ⚠️ 這不是筆誤。後端以 APScheduler 的 CronTrigger.from_crontab 驅動，它把
    // day-of-week 直接塞進自己的欄位（0=Monday），不做標準 crontab（0=Sunday）的轉換。
    // 此處若照標準 crontab 渲染，畫面會與實際觸發日整整差一天。
    expect(formatCronSchedule("0 10 * * 0")).toBe("每週一 10:00 UTC")
    expect(formatCronSchedule("0 10 * * 1")).toBe("每週二 10:00 UTC")
    expect(formatCronSchedule("30 6 * * 6")).toBe("每週日 06:30 UTC")
  })

  it("每月（指定日、dow 為 *）", () => {
    expect(formatCronSchedule("0 9 1 * *")).toBe("每月 1 日 09:00 UTC")
  })

  it("時與分補零", () => {
    expect(formatCronSchedule("5 9 * * *")).toBe("每日 09:05 UTC")
  })

  it("無法判讀者回 null，交由呼叫端退回顯示原始運算式", () => {
    expect(formatCronSchedule("*/15 * * * *")).toBeNull() // 間隔式
    expect(formatCronSchedule("0 10 * * 1-5")).toBeNull() // 範圍
    expect(formatCronSchedule("0 10 1 * 1")).toBeNull() // dom 與 dow 同時指定
    expect(formatCronSchedule("0 10 * 3 *")).toBeNull() // 指定月份
    expect(formatCronSchedule("0 10 * *")).toBeNull() // 欄位數不足
    expect(formatCronSchedule("")).toBeNull()
    expect(formatCronSchedule(null)).toBeNull()
  })

  it("超出範圍的值視為無法判讀，不得算出不存在的星期", () => {
    // 邊界：dow 只到 6。若寬鬆處理會索引到 undefined 而渲染出「每週undefined」。
    expect(formatCronSchedule("0 10 * * 7")).toBeNull()
    expect(formatCronSchedule("0 24 * * *")).toBeNull()
    expect(formatCronSchedule("60 8 * * *")).toBeNull()
  })
})
