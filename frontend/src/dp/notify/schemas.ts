import { z } from "zod"

/**
 * 一次性連結類變數（#50）：主旨不得使用，只能放內文。
 *
 * 後端 `app/dp/notify/redaction.py` 的 `ONE_TIME_LINK_VARIABLES` 之鏡像——新增連結類變數時兩處一起改。
 * 此處僅供即時提示；權限邊界在後端（`DP_MAIL_013`），兩邊不一致時以後端為準。
 */
export const ONE_TIME_LINK_VARIABLES = ["reset_link", "verify_link", "activate_link"] as const

// 與後端渲染一致：`{{` 是跳脫後的字面 `{`，所以要看變數前連續 `{` 的奇偶——
// `{reset_link}` / `{{{reset_link}}}`（字面 `{` + 代入）會代入連結 → 擋；`{{reset_link}}` 是字面文字 → 不擋。
// `(?:![rsa])?` 涵蓋轉換旗標（`{reset_link!s}` 同樣會代入）。
const _SUBJECT_LINK_PATTERN = new RegExp(
  `(?<!\\{)(?:\\{\\{)*\\{(?:${ONE_TIME_LINK_VARIABLES.join("|")})(?:![rsa])?\\}`,
)

const _SubjectSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入主旨" })
  .max(200, { message: "主旨不可超過 200 字" })
  .refine((v) => !_SUBJECT_LINK_PATTERN.test(v), {
    message: "主旨不得使用重設、驗證或啟用連結等一次性連結變數，請改放於內文",
  })

/** 通知範本編輯驗證（US9），命名對齊後端 Pydantic `TemplateUpdate`。 */
export const TemplateUpdateSchema = z.object({
  subject: _SubjectSchema,
  body: z.string().min(1, { message: "請輸入內文" }).max(10000, { message: "內文不可超過 10000 字" }),
  channel: z.enum(["EMAIL", "MSG", "BOTH"], { message: "請選擇管道" }),
  is_enabled: z.boolean(),
  version: z.number().int(),
})

export type TemplateUpdateValues = z.infer<typeof TemplateUpdateSchema>

/** 範本內容編輯表單驗證（主旨 / 內文；管道與啟停於清單行內操作）。 */
export const TemplateContentSchema = z.object({
  subject: _SubjectSchema,
  body: z.string().min(1, { message: "請輸入內文" }).max(10000, { message: "內文不可超過 10000 字" }),
})

export type TemplateContentValues = z.infer<typeof TemplateContentSchema>
