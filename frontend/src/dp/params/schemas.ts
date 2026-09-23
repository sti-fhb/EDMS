import { z } from "zod"

/** 明細說明：選填、trim、≤500。對齊後端 ParamDetailUpdate / ParamDetailCreate 的 description。 */
export const ParamDescriptionSchema = z
  .string()
  .trim()
  .max(500, { message: "說明長度不可超過 500 字元" })

/** 新增清單項：碼（英數底線）+ 中文名稱 + 說明（選填）。對齊後端 ParamDetailCreate。 */
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
  description: ParamDescriptionSchema,
})

export type ParamItemCreateValues = z.infer<typeof ParamItemCreateSchema>

/** 清單項名稱：非空 ≤100。與 ParamItemCreateSchema.param_name 同限制，對齊後端 _NameStr。 */
export const ParamItemNameSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入內容" })
  .max(100, { message: "名稱長度不可超過 100 字元" })

/**
 * 受控項名稱：非空 ≤50。上限取各模組**最窄**之欄位（DM_CATEGORY.CATEGORY_NAME /
 * DM_TAG.TAG_NAME / ET_TAG.TAG_NAME 皆為 VARCHAR(50)），與後端 `_ControlledNameStr` 同值。
 *
 * 取捨：DM_FUNC.FUNC_NAME 實為 VARCHAR(100)，於此一併收斂至 50——各 kind 共用同一輸入元件，
 * 依 kind 給不同上限會讓「同一顆新增鈕有時能打 100 字」，判斷成本高於那 50 字的價值。
 */
export const ControlledNameSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入名稱" })
  .max(50, { message: "名稱長度不可超過 50 字元" })

/** 受控項代碼：英數、≤10（DM_CATEGORY.CATEGORY_CODE / DM_FUNC.FUNC_CODE）。格式權威檢核仍在模組端。 */
export const ControlledCodeSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入代碼" })
  .max(10, { message: "代碼長度不可超過 10 字元" })
  .regex(/^[A-Za-z0-9]+$/, { message: "代碼僅允許英文與數字" })

/** 編輯參數值：非空 ≤500。伺服器端做型別 / 值域權威檢核。 */
export const ParamValueSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入內容" })
  .max(500, { message: "長度不可超過 500 字元" })