/**
 * 再開課之新起訖時間驗證（US11 / FR-ET-US11-09 / #288）。
 *
 * 獨立成模組而非留在元件檔（原為 `ReopenCourseDialog.tsx`，#428 起併入
 * `CourseEditorPage`）：元件檔匯出非元件會破壞 Fast Refresh
 * （`react-refresh/only-export-components`），而這是再開課唯一會算錯的邏輯。
 *
 * ⚠️ 起始時間規則與 `CourseEditorPage.validateForm` **相反**：本頁平時擋「起始早於
 * 當下」，再開課刻意允許（補開一段已經開始的期間）。兩者不可互相代用。
 */

import type { Dayjs } from "dayjs"

/** 逐欄錯誤訊息；空物件 = 通過。 */
export interface ReopenScheduleErrors {
  start?: string
  end?: string
}

/**
 * 驗證再開課的新起訖時間，回傳逐欄錯誤訊息。
 *
 * 三條規則，對齊後端：
 *
 * | 規則 | 後端對應 |
 * |---|---|
 * | 兩者皆必填 | `ReopenCourseReq._schedule_required` |
 * | 訖止須晚於起始 | `_CourseFields._end_after_start` |
 * | 訖止須嚴格晚於當下 | `rules.ensure_reopen_schedule`（422 `ET_COURSE_008`）|
 *
 * ⚠️ **起始刻意不檢核「須 ≥ 當下」**，與後端一致：「補開一段已經開始的期間」是合理
 * 操作（教師想讓學員從上週就能看）。前端若擅自加上那條，會擋掉後端允許的合法操作，
 * 而畫面上不會有任何線索說明為什麼不給送。
 *
 * @param now 由呼叫端傳入而非在此取 `dayjs()`——否則「訖止須晚於當下」這條測不了。
 */
export function validateReopenSchedule(
  startAt: Dayjs | null,
  endAt: Dayjs | null,
  now: Dayjs,
): ReopenScheduleErrors {
  const errors: ReopenScheduleErrors = {}
  if (!startAt) errors.start = "請選擇新的開放起始時間"
  if (!endAt) {
    errors.end = "請選擇新的開放訖止時間"
    return errors
  }
  // 「晚於起始」優先於「晚於當下」：起始填了 2027 而訖止填 2026 時，「須晚於起始」
  // 才是教師真正犯的錯；先報「須晚於目前時間」會把他導向去改一個沒問題的欄位。
  if (startAt && !endAt.isAfter(startAt)) errors.end = "課程訖止時間須晚於起始時間"
  else if (!endAt.isAfter(now)) errors.end = "課程訖止時間須晚於目前時間"
  return errors
}
