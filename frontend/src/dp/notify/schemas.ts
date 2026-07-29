import { z } from "zod"

/** 通知範本編輯驗證（US9），命名對齊後端 Pydantic `TemplateUpdate`。 */
export const TemplateUpdateSchema = z.object({
  subject: z.string().trim().min(1, { message: "請輸入主旨" }).max(200, { message: "主旨不可超過 200 字" }),
  body: z.string().min(1, { message: "請輸入內文" }),
  channel: z.enum(["EMAIL", "MSG", "BOTH"], { message: "請選擇管道" }),
  is_enabled: z.boolean(),
  version: z.number().int(),
})

export type TemplateUpdateValues = z.infer<typeof TemplateUpdateSchema>