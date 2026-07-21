import { z } from "zod"

// 密碼字元類型（大寫 / 小寫 / 數字 / 特殊符號），對齊後端 password_policy 複雜度判定。
const CHAR_CLASSES = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9\s]/]

/** 密碼重設表單驗證（US3），命名對齊後端 Pydantic `ResetPasswordRequest`。 */
export const ResetPasswordSchema = z
  .object({
    new_password: z
      .string()
      .min(8, { message: "密碼至少 8 字元" })
      .refine((p) => CHAR_CLASSES.filter((re) => re.test(p)).length >= 3, {
        message: "密碼須含大小寫英文 / 數字 / 特殊符號至少 3 種",
      }),
    confirm_password: z.string().min(1, { message: "請再次輸入密碼" }),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    message: "兩次輸入之密碼不一致",
    path: ["confirm_password"],
  })

export type ResetPasswordValues = z.infer<typeof ResetPasswordSchema>
