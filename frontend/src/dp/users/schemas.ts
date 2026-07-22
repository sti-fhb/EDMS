import { z } from "zod"

// 密碼字元類型（大小寫 / 數字 / 特殊符號），對齊後端 password_policy 複雜度判定（同 registerSchema）。
const CHAR_CLASSES = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9\s]/]

const emailField = z
  .string()
  .trim()
  .min(1, { message: "請輸入 Email" })
  .max(255, { message: "Email 長度不可超過 255 字元" })
  .email({ message: "Email 格式不正確" })

const nameField = z
  .string()
  .trim()
  .min(1, { message: "請輸入姓名" })
  .max(50, { message: "姓名長度不可超過 50 字元" })

/** 建立帳號表單驗證（US4 FR-03），命名對齊後端 `UserCreate`。 */
export const UserCreateSchema = z.object({
  email: emailField,
  user_name: nameField,
  password: z
    .string()
    .min(8, { message: "初始密碼至少 8 字元" })
    .refine((p) => CHAR_CLASSES.filter((re) => re.test(p)).length >= 3, {
      message: "密碼須含大小寫英文 / 數字 / 特殊符號至少 3 種",
    }),
})

/** 基本資料維護表單驗證（US4 FR-06）。 */
export const UserUpdateSchema = z.object({
  user_name: nameField,
  email: emailField,
})

export type UserCreateValues = z.infer<typeof UserCreateSchema>
export type UserUpdateValues = z.infer<typeof UserUpdateSchema>
