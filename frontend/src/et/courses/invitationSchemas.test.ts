import { describe, expect, it } from "vitest"

import {
  InviteEmailsSchema,
  MAX_EMAILS_PER_REQUEST,
  invalidEmails,
  parseEmails,
} from "./invitationSchemas"

/** 取第一則錯誤訊息（`safeParse` 失敗時）。 */
function firstError(emails: string): string | undefined {
  const result = InviteEmailsSchema.safeParse({ emails })
  return result.success ? undefined : result.error.issues[0]?.message
}

describe("parseEmails：教師是用貼的，格式什麼樣子都有", () => {
  it("換行、逗號、分號與全形分隔都吃", () => {
    expect(parseEmails("a@x.gov.tw\nb@x.gov.tw,c@x.gov.tw；d@x.gov.tw，e@x.gov.tw")).toEqual([
      "a@x.gov.tw",
      "b@x.gov.tw",
      "c@x.gov.tw",
      "d@x.gov.tw",
      "e@x.gov.tw",
    ])
  })

  it("正規化為小寫", () => {
    expect(parseEmails("A@X.GOV.TW")).toEqual(["a@x.gov.tw"])
  })

  it("去重且保留首次出現順序", () => {
    expect(parseEmails("b@x.gov.tw, a@x.gov.tw, B@x.gov.tw")).toEqual(["b@x.gov.tw", "a@x.gov.tw"])
  })

  it("空白輸入回空陣列", () => {
    expect(parseEmails("  \n ")).toEqual([])
  })
})

describe("InviteEmailsSchema", () => {
  it("空白輸入提示至少一筆", () => {
    expect(firstError("   ")).toBe("請至少輸入一筆 Email")
  })

  it("格式錯誤時列出是哪幾筆", () => {
    // 只說「格式不正確」等於要教師自己一行一行找
    expect(firstError("ok@x.gov.tw\nbroken\nalso-bad")).toBe("以下 Email 格式不正確：broken、also-bad")
  })

  it("超過上限時附上實際筆數", () => {
    const raw = Array.from({ length: MAX_EMAILS_PER_REQUEST + 2 }, (_, i) => `u${i}@x.gov.tw`).join(",")
    expect(firstError(raw)).toBe(`單次最多邀請 ${MAX_EMAILS_PER_REQUEST} 筆，目前為 ${MAX_EMAILS_PER_REQUEST + 2} 筆`)
  })

  it("去重後才算上限——貼了很多次但其實只有兩個人不該被擋", () => {
    const raw = Array.from({ length: 60 }, () => "a@x.gov.tw,b@x.gov.tw").join(",")
    expect(firstError(raw)).toBeUndefined()
  })

  it("恰好等於上限可通過", () => {
    const raw = Array.from({ length: MAX_EMAILS_PER_REQUEST }, (_, i) => `u${i}@x.gov.tw`).join("\n")
    expect(firstError(raw)).toBeUndefined()
  })
})

describe("invalidEmails", () => {
  it.each(["not-an-email", "a@", "@x.gov.tw", "a@x"])("%s 視為不合法", (raw) => {
    expect(invalidEmails(raw)).toEqual([raw.toLowerCase()])
  })

  it("合法者不列入", () => {
    expect(invalidEmails("a@x.gov.tw\nb@y.com.tw")).toEqual([])
  })
})
