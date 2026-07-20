import { z } from "zod"

// 密碼字元類型（大寫 / 小寫 / 數字 / 特殊符號），對齊後端 password_policy 之複雜度判定。
const CHAR_CLASSES = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9\s]/]

/** 自助註冊表單驗證（US2），命名對齊後端 Pydantic `RegisterRequest`。 */
export const RegisterRequestSchema = z
  .object({
    email: z
      .string()
      .min(1, { message: "請輸入 Email" })
      .email({ message: "Email 格式不正確" }),
    user_name: z
      .string()
      .min(1, { message: "請輸入姓名" })
      .max(50, { message: "姓名長度不可超過 50 字元" }),
    password: z
      .string()
      .min(8, { message: "密碼至少 8 字元" })
      .refine((p) => CHAR_CLASSES.filter((re) => re.test(p)).length >= 3, {
        message: "密碼須含大小寫英文 / 數字 / 特殊符號至少 3 種",
      }),
    confirm_password: z.string().min(1, { message: "請再次輸入密碼" }),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: "兩次輸入之密碼不一致",
    path: ["confirm_password"],
  })

export type RegisterRequestValues = z.infer<typeof RegisterRequestSchema>
