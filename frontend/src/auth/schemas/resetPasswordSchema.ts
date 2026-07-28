import { z } from "zod"

// 密碼字元類型（大寫 / 小寫 / 數字 / 特殊符號），對齊後端 password_policy 複雜度判定。
const CHAR_CLASSES = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9\s]/]

/**
 * 密碼重設表單驗證（US3；帳號啟用 US4 亦重用），命名對齊後端 Pydantic `ResetPasswordRequest`。
 *
 * minLen / charTypes 由密碼政策動態帶入（usePasswordPolicy，#77），使前端提示與驗證跟著參數變、非寫死；
 * 後端仍為權威。仿 US8 `makeChangePasswordSchema`。
 */
export function makeResetPasswordSchema(minLen = 8, charTypes = 3) {
  return z
    .object({
      new_password: z
        .string()
        .min(minLen, { message: `密碼至少 ${minLen} 字元` })
        .refine((p) => CHAR_CLASSES.filter((re) => re.test(p)).length >= charTypes, {
          message: `密碼須含大小寫英文 / 數字 / 特殊符號至少 ${charTypes} 種`,
        }),
      confirm_password: z.string().min(1, { message: "請再次輸入密碼" }),
    })
    .refine((d) => d.new_password === d.confirm_password, {
      message: "兩次輸入之密碼不一致",
      path: ["confirm_password"],
    })
}

export type ResetPasswordValues = z.infer<ReturnType<typeof makeResetPasswordSchema>>
