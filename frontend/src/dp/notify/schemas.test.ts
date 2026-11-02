// @vitest-environment node
// 純邏輯測試：不碰 DOM、不發請求，跳過 jsdom（同 et/courses/invitationSchemas.test.ts）。
import { describe, expect, it } from "vitest"

import { TemplateContentSchema } from "./schemas"

const LINK_MSG = "主旨不得使用重設、驗證或啟用連結等一次性連結變數，請改放於內文"

/** 取主旨欄位的第一則錯誤訊息；通過時回 undefined。 */
function subjectError(subject: string): string | undefined {
  const result = TemplateContentSchema.safeParse({ subject, body: "內文" })
  return result.success ? undefined : result.error.issues.find((i) => i.path[0] === "subject")?.message
}

describe("主旨禁用一次性連結變數（#50）：判斷與後端渲染一致", () => {
  it.each([
    "密碼重設 {reset_link}",
    "{verify_link}",
    "請啟用 {activate_link}",
    "{reset_link!s}", // 轉換旗標同樣會代入
    "{{{reset_link}}}", // 字面 `{` + 代入連結 + 字面 `}`
  ])("會代入連結 → 擋：%s", (subject) => {
    expect(subjectError(subject)).toBe(LINK_MSG)
  })

  it.each([
    "【EDMS】密碼重設通知",
    "{user_name} 的密碼重設通知",
    "{{reset_link}}", // 跳脫後是字面文字
    "reset_link",
  ])("不會代入連結 → 放行：%s", (subject) => {
    expect(subjectError(subject)).toBeUndefined()
  })
})
