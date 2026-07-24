import { z } from "zod"

/** 新增清單項：碼（英數底線）+ 中文名稱。對齊後端 ParamDetailCreate。 */
export const ParamItemCreateSchema = z.object({
  param_key: z
    .string()
    .trim()
    .min(1, { message: "請輸入代碼" })
    .max(50, { message: "代碼長度不可超過 50 字元" })
    .regex(/^[A-Za-z0-9_]+$/, { message: "代碼僅允許英文、數字及底線" }),
  param_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入名稱" })
    .max(100, { message: "名稱長度不可超過 100 字元" }),
})

export type ParamItemCreateValues = z.infer<typeof ParamItemCreateSchema>

/** 編輯參數值 / 清單項名稱：非空。伺服器端做型別 / 值域權威檢核。 */
export const ParamValueSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入內容" })
  .max(500, { message: "長度不可超過 500 字元" })