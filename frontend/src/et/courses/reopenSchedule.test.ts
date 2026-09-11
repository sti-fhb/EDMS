import dayjs from "dayjs"
import { describe, expect, it } from "vitest"

import { validateReopenSchedule } from "./reopenSchedule"

const NOW = dayjs("2026-09-09T12:00:00Z")

describe("validateReopenSchedule（US11 / #288）", () => {
  it("兩者皆填且訖止在未來 → 通過", () => {
    expect(validateReopenSchedule(NOW.subtract(1, "day"), NOW.add(30, "day"), NOW)).toEqual({})
  })

  it("起始留空 → 標示起始欄", () => {
    expect(validateReopenSchedule(null, NOW.add(30, "day"), NOW)).toEqual({
      start: "請選擇新的開放起始時間",
    })
  })

  it("訖止留空 → 標示訖止欄", () => {
    expect(validateReopenSchedule(NOW, null, NOW).end).toBe("請選擇新的開放訖止時間")
  })

  it("兩者皆留空 → 兩欄都標示", () => {
    // FR-ET-US11-09「強制要求重新設定一組新的起訖時間」——視窗兩欄皆不預填，
    // 教師直接按確認時必須兩欄都指出來，只標一欄他會以為另一欄沒問題。
    const errors = validateReopenSchedule(null, null, NOW)
    expect(errors.start).toBe("請選擇新的開放起始時間")
    expect(errors.end).toBe("請選擇新的開放訖止時間")
  })

  it("訖止早於起始 → 報「須晚於起始」而非「須晚於目前時間」", () => {
    // 起始 2027、訖止 2026 時，教師真正犯的錯是順序顛倒。先報「須晚於目前時間」
    // 會把他導向去改一個其實沒問題的欄位。
    const errors = validateReopenSchedule(NOW.add(1, "year"), NOW.add(300, "day"), NOW)
    expect(errors.end).toBe("課程訖止時間須晚於起始時間")
  })

  it("訖止等於起始 → 不通過（須嚴格晚於）", () => {
    const at = NOW.add(10, "day")
    expect(validateReopenSchedule(at, at, NOW).end).toBe("課程訖止時間須晚於起始時間")
  })

  it("訖止已過 → 報「須晚於目前時間」（對齊後端 ET_COURSE_008）", () => {
    // 少了這條，直呼 API 或畫面誤填就能造出「已發布但期間已過」的課程：教師端看到
    // 「已發布」，學員端卻被 `is_effectively_closed` 判為視同關閉而進不去。
    const errors = validateReopenSchedule(NOW.subtract(30, "day"), NOW.subtract(1, "day"), NOW)
    expect(errors.end).toBe("課程訖止時間須晚於目前時間")
  })

  it("訖止恰為當下 → 不通過（後端為嚴格大於）", () => {
    expect(validateReopenSchedule(NOW.subtract(1, "day"), NOW, NOW).end).toBe(
      "課程訖止時間須晚於目前時間",
    )
  })

  it("起始落在過去但訖止在未來 → 通過（不檢核起始）", () => {
    // 「補開一段已經開始的期間」是合理操作。後端 `ensure_reopen_schedule` 刻意只檢核
    // 訖止，前端若加上「起始須 ≥ 當下」會擋掉後端允許的操作。
    expect(validateReopenSchedule(NOW.subtract(1, "year"), NOW.add(1, "day"), NOW)).toEqual({})
  })
})
