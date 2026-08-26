import { z } from "zod"

/**
 * 自助註冊表單驗證（US2），命名對齊後端 Pydantic `RegisterRequest`。
 *
 * **不含密碼欄位**（#212）：註冊只收 Email 與姓名，密碼於使用者點驗證連結後在驗證頁當場
 * 設定，其複雜度驗證重用 `makeResetPasswordSchema`（依 PWD_POLICY 動態）。因此本 schema
 * 不需要密碼政策參數，改為單一常數而非工廠函式。
 */
export const registerRequestSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, { message: "請輸入 Email" })
    .max(255, { message: "Email 長度不可超過 255 字元" })
    .email({ message: "Email 格式不正確" }),
  user_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入姓名" })
    .max(50, { message: "姓名長度不可超過 50 字元" }),
})

export type RegisterRequestValues = z.infer<typeof registerRequestSchema>
