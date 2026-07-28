import { z } from "zod"

// 密碼字元類型（大寫 / 小寫 / 數字 / 特殊符號），對齊後端 password_policy 複雜度判定。
const CHAR_CLASSES = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9\s]/]

/** 姓名變更表單驗證（US8），對齊後端 `NameUpdate`（DP_USER.USER_NAME 長度 50）。 */
export const NameSchema = z.object({
  user_name: z.string().trim().min(1, { message: "請輸入姓名" }).max(50, { message: "姓名不可超過 50 字" }),
})

/** Email 變更表單驗證（US8），對齊後端 `EmailChangeRequest`；唯一性由後端權威檢核。 */
export const EmailChangeSchema = z.object({
  new_email: z.string().trim().email({ message: "請輸入有效的 Email" }).max(255, { message: "Email 過長" }),
})

/**
 * 密碼變更表單驗證（US8）。
 *
 * minLen / charTypes 由密碼政策動態帶入（usePasswordPolicy），使前端提示與檢核跟著參數變、非寫死；
 * 後端仍為權威（含特權 12 判定）。命名對齊後端 `PasswordChange`。
 */
export function makeChangePasswordSchema(minLen = 8, charTypes = 3) {
  return z
    .object({
      old_password: z.string().min(1, { message: "請輸入舊密碼" }),
      new_password: z
        .string()
        .min(minLen, { message: `密碼至少 ${minLen} 字元` })
        .refine((p) => CHAR_CLASSES.filter((re) => re.test(p)).length >= charTypes, {
          message: `密碼須含大小寫英文 / 數字 / 特殊符號至少 ${charTypes} 種`,
        }),
      confirm_password: z.string().min(1, { message: "請再次輸入新密碼" }),
    })
    .refine((d) => d.new_password === d.confirm_password, {
      message: "兩次輸入之新密碼不一致",
      path: ["confirm_password"],
    })
}
