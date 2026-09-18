import { z } from "zod"

/** 單次可邀請之 Email 數上限（對齊後端 `MAX_EMAILS_PER_REQUEST`）。 */
export const MAX_EMAILS_PER_REQUEST = 50

/**
 * 收件人輸入之分隔字元：換行、逗號、分號，以及從 Excel / 通訊軟體貼進來常見的全形版本。
 * 與後端 `app/et/invitation/rules.py` 之 `_SEPARATORS` 同一組。
 */
const SEPARATORS = /[\s,;，、；]+/

/** 與後端 `_EMAIL_PATTERN` 同一條——刻意保守，寬鬆比對只會讓錯字變成一封寄不到的信。 */
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/

/**
 * 整段輸入 → 正規化、去重後之 Email 清單。
 *
 * 與後端同規則（小寫化、去重、保留首次出現順序）——前端先擋是為了讓教師**當場**看到
 * 哪裡打錯，而不是送出後才收到一個 422；後端仍會重跑一次，這裡不是把關。
 */
export function parseEmails(raw: string): string[] {
  const seen = new Set<string>()
  for (const token of raw.split(SEPARATORS)) {
    if (token !== "") seen.add(token.toLowerCase())
  }
  return [...seen]
}

/** 找出格式不合法者（供錯誤訊息列出「是哪幾筆」）。 */
export function invalidEmails(raw: string): string[] {
  return parseEmails(raw).filter((email) => !EMAIL_PATTERN.test(email))
}

/**
 * 收件人輸入之驗證。
 *
 * 錯誤訊息刻意**列出實際有問題的那幾筆**：教師一次貼十幾筆進來，只說「格式不正確」
 * 等於要他自己一行一行找。
 */
export const InviteEmailsSchema = z
  .object({ emails: z.string() })
  .superRefine((value, ctx) => {
    const parsed = parseEmails(value.emails)
    if (parsed.length === 0) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["emails"], message: "請至少輸入一筆 Email" })
      return
    }
    const invalid = invalidEmails(value.emails)
    if (invalid.length > 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["emails"],
        message: `以下 Email 格式不正確：${invalid.join("、")}`,
      })
      return
    }
    if (parsed.length > MAX_EMAILS_PER_REQUEST) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["emails"],
        message: `單次最多邀請 ${MAX_EMAILS_PER_REQUEST} 筆，目前為 ${parsed.length} 筆`,
      })
    }
  })

export type InviteEmailsValues = z.infer<typeof InviteEmailsSchema>

/**
 * 邀請信預覽（唯讀）。
 *
 * **內容與收件人無關**：後端以佔位字樣取代收件人姓名（逐收件人不同），其餘（課程名稱、
 * 閱課期間、邀請碼、學習連結）人人相同。因此改動 Email 清單**不需要**重新預覽，也不
 * 回傳收件人範例或筆數（筆數前端自己用 `parseEmails` 算）。
 */
export interface InvitePreview {
  subject: string
  body: string
}

/**
 * 寄出結果（#362：邀請即加入）。
 *
 * `joined` 與 `mailFailed` **刻意分開**，且不可在畫面上合成一句話：加入成功而信寄失敗
 * 是一個真實且**無法補救**的組合（待加入清單與重寄功能隨 #362 一起移除）。說成
 * 「寄出 N 筆、失敗 M 筆」會讓教師以為失敗的那幾位沒進課程，而他們其實已經在學員
 * 清單裡了。
 */
export interface EmailInviteResult {
  joined: number
  mail_failed: string[]
}
