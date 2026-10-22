import type { Dayjs } from "dayjs"

import type { AudienceDraft } from "./schemas"

/** 課程基本資料表單的形狀——與 `CourseEditorPage` 的 `EMPTY_FORM` 同構。 */
export interface CourseBasicForm {
  course_name: string
  description: string
  require_approval: boolean
  audiences: AudienceDraft[]
}

/**
 * 基本資料的可比對快照（#804 ①）——判斷「有沒有未按儲存草稿的修改」。
 *
 * ## 為什麼草稿按「取消」需要它
 *
 * #631 只把**已發布 / 已關閉**的內容編輯改成暫存；草稿維持**即時寫入活表**。於是草稿按
 * 「取消」之後兩半的命運相反：章節 / 教材 / 測驗 / 問卷**已經存進課程**、取消還原不了，
 * 而尚未按「儲存草稿」的基本資料則**靜默丟掉**。ET05 據此在有未存修改時先問一次。
 *
 * ## 🔴 用快照比對、不用 dirty flag
 *
 * 教師改了又改回原值時不該跳視窗說「不會保留」——那時根本沒有東西可保留。dirty flag
 * 一旦設上就回不去，必然誤報。
 *
 * ⚠️ 日期轉 ISO 而非直接塞 `Dayjs`：同一個時刻的兩個 `Dayjs` 實例 `JSON.stringify` 得到
 * 的字串相同，但這裡明寫轉換，免得日後有人換掉欄位型別時靜默失準。
 *
 * 🔴 **快照只在載入課程時寫一次**，`invalidate()` 觸發的 refetch 不會刷新它。目前不會
 * 誤報，是因為**儲存草稿成功後一定導離本頁**（`saveMut.onSuccess` → `navigate`），
 * 「存完留在原地再按取消」這條路徑不存在。⚠️ 日後若把儲存改成留在原地，呼叫端必須跟著
 * 重設快照，否則每次按取消都會跳出「不會保留」的假警報（#804 security review LOW-2）。
 *
 * ℹ️ 本函式獨立成檔而非留在 `CourseEditorPage.tsx`：元件檔同時匯出元件與函式會讓
 * `react-refresh/only-export-components` 告警，且測試得為了一個純函式把整個元件模組
 * （MUI、各 service）拉進來——實測 import 佔 10 秒、測試本身只花 21 毫秒。
 */
export function serializeBasic(form: CourseBasicForm, startAt: Dayjs | null, endAt: Dayjs | null): string {
  return JSON.stringify({
    course_name: form.course_name,
    description: form.description,
    require_approval: form.require_approval,
    audiences: form.audiences.map(({ unit_tag_id, tag_id }) => [unit_tag_id, tag_id]),
    start: startAt && startAt.isValid() ? startAt.toISOString() : null,
    end: endAt && endAt.isValid() ? endAt.toISOString() : null,
  })
}
