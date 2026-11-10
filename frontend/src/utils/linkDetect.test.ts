import { describe, expect, it } from "vitest"
import { registerRequestSchema } from "../auth/schemas/registerSchema"
import { NameSchema } from "../dp/user/schemas/profileSchemas"
import { UserCreateSchema, UserUpdateSchema } from "../dp/users/schemas"
import { containsLink, NAME_LINK_MESSAGE } from "./linkDetect"

// 對齊後端 tests/unit/test_core_link_scan.py：前端只做即時提示，權威在後端（#942）
describe("containsLink", () => {
  it.each([
    "https://evil.example.com",
    "HTTPS://EVIL.EXAMPLE.COM",
    "帳號異常請至 https://evil.example.com 處理",
    "ftp://evil.example.com",
    "//evil.example.com/x",
    "www.evil.example.com",
    "WWW.EVIL.EXAMPLE.COM",
    "-www.evil.example.com",
    ".https://evil.example.com",
    "1https://evil.example.com",
    "ｈｔｔｐｓ://evil.example.com", // 全形協定
    "ｗｗｗ．evil．example．com", // 全形 www 與句點
    "請至https://evil.example.com處理",
    "h\u00adttps://evil.example.com", // 軟連字號
    "www\u200b.evil.example.com", // 零寬空白
    "請至 www。evil.example.com", // U+3002 當成句點
  ])("含網址：%s", (text) => {
    expect(containsLink(text)).toBe(true)
  })

  it.each([
    "王小明",
    "John Smith",
    "J. Smith",
    "O'Brien",
    "Mary-Jane Watson",
    "A/B 組",
    "a//b",
    "張三 // 李四",
    "lawww.example",
    "v1.2",
    "user@example.com",
    "",
  ])("不含網址：%s", (text) => {
    expect(containsLink(text)).toBe(false)
  })
})

describe("UNC 路徑（#942）", () => {
  // 反斜線以字元碼組出，不在原始碼直接寫跳脫序列
  const bs = String.fromCodePoint(92)
  const unc = `${bs}${bs}evil.example.com${bs}share`

  it.each([unc, `請至 ${unc} 下載`, `${bs}${bs}10.0.0.1${bs}x`, `-${unc}`])("含 UNC：%s", (text) => {
    expect(containsLink(text)).toBe(true)
  })

  it.each([`a${bs}${bs}b`, `${bs}${bs} 後面接空白`, `王${bs}小明`])("不是 UNC：%s", (text) => {
    expect(containsLink(text)).toBe(false)
  })
})

describe("三處姓名欄位 schema 皆拒絕網址", () => {
  const name = "帳號異常請至 https://evil.example.com 處理"
  const cases = [
    ["自助註冊", () => registerRequestSchema.safeParse({ email: "a@example.com", user_name: name })],
    ["本人改姓名", () => NameSchema.safeParse({ user_name: name })],
    ["管理者新增", () => UserCreateSchema.safeParse({ email: "a@example.com", user_name: name })],
    ["管理者修改", () => UserUpdateSchema.safeParse({ user_name: name })],
  ] as const

  it.each(cases)("%s", (_label, parse) => {
    const result = parse()
    expect(result.success).toBe(false)
    expect(result.error?.issues.map((i) => i.message)).toContain(NAME_LINK_MESSAGE)
  })

  it("正常姓名照常通過（正向錨點）", () => {
    expect(NameSchema.safeParse({ user_name: "J. Smith" }).success).toBe(true)
    expect(UserUpdateSchema.safeParse({ user_name: "王小明" }).success).toBe(true)
  })
})
