// `basicSnapshot.serializeBasic` 的單元測試（#804）。
//
// 本檔自 CourseEditorPage.test.tsx 拆出，函式本身也一併搬出元件檔——留在那裡會讓
// `react-refresh/only-export-components` 告警（元件檔同時匯出元件與函式），而且測試得
// 為了一個純函式把整個元件模組拉進來：實測 import 佔 10 秒、測試本身只花 21 毫秒。
import dayjs from "dayjs"
import { describe, expect, it } from "vitest"

import { serializeBasic } from "./basicSnapshot"

describe("serializeBasic：每個欄位都要算進快照（#804 ①）", () => {
  // ## 為什麼拆成 unit 測試
  //
  // code review 指出：上面那組流程測試**只改課名**，所以把 `description`、
  // `require_approval`、`audiences`、`start`、`end` 任一欄位從 `serializeBasic` 拿掉，
  // 全部測試照樣綠。漏報的後果正是這個 PR 要修的缺陷——教師改了說明、按取消、
  // 沒有視窗、說明靜默丟掉。
  //
  // 逐欄位走 UI 會很慢（MUI DateTimePicker 一個欄位 12 個按鍵、受訓對象要開下拉），
  // 而這是個**純函式**——依 `.claude/rules/sti-testing.md`「拿掉真 DB 還驗得了嗎」的
  // 分層閘門，驗得了就寫 unit。
  const BASE = {
    course_name: "採血作業訓練",
    description: "課程說明",
    require_approval: false,
    audiences: [{ unit_tag_id: 101, tag_id: 2 }],
  }
  const START = dayjs("2099-01-01T00:00:00Z")
  const END = dayjs("2099-12-31T00:00:00Z")
  const base = () => serializeBasic(BASE, START, END)

  it.each([
    ["課程名稱", { ...BASE, course_name: "採血作業訓練（新）" }, START, END],
    ["課程說明", { ...BASE, description: "改過的說明" }, START, END],
    ["需線下核可", { ...BASE, require_approval: true }, START, END],
    ["受訓對象改值", { ...BASE, audiences: [{ unit_tag_id: 101, tag_id: 3 }] }, START, END],
    ["受訓對象增一列", { ...BASE, audiences: [...BASE.audiences, { unit_tag_id: 102, tag_id: 4 }] }, START, END],
    ["受訓對象清空", { ...BASE, audiences: [] }, START, END],
    ["起始時間", BASE, dayjs("2098-01-01T00:00:00Z"), END],
    ["訖止時間", BASE, START, dayjs("2098-12-31T00:00:00Z")],
    ["起始清空", BASE, null, END],
    ["訖止清空", BASE, START, null],
  ])("改 %s 會讓快照不同", (_label, form, start, end) => {
    expect(serializeBasic(form, start, end)).not.toBe(base())
  })

  it("同樣的值得到同樣的快照——「改了又改回」不算修改", () => {
    // 🔴 這條是「用快照比對而非 dirty flag」的理由本身。dirty flag 一旦設上就回不去，
    // 教師把字改掉又改回來仍會被告知「不會保留」——而那時根本沒有東西可保留。
    expect(serializeBasic({ ...BASE }, dayjs(START.toISOString()), dayjs(END.toISOString()))).toBe(base())
  })

  it("日期只看時刻、不看 Dayjs 實例（載入端與比對端走同一條轉換）", () => {
    // 載入時是 `dayjs(course.open_start_at)`，比對時是當下的 `startAt`——兩個不同的
    // 實例。若比對的是物件本身而非 ISO 字串，每次 render 都會被判成已修改。
    expect(serializeBasic(BASE, dayjs(START.valueOf()), END)).toBe(base())
  })
})
