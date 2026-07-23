import { z } from "zod"

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

/** 建立帳號表單驗證（US4 #67 邀請流程）：管理者不設密碼，僅 Email / 姓名。命名對齊後端 `UserCreate`。 */
export const UserCreateSchema = z.object({
  email: emailField,
  user_name: nameField,
})

/** 編輯表單驗證（US4 #67）：僅可改姓名；Email 為登入帳號、唯讀不在此 schema。 */
export const UserUpdateSchema = z.object({
  user_name: nameField,
})

export type UserCreateValues = z.infer<typeof UserCreateSchema>
export type UserUpdateValues = z.infer<typeof UserUpdateSchema>
