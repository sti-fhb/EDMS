import { z } from "zod"

/** 廢止附件格式白名單（比照文件上傳；與後端 DM_FILE_TYPES / wireframe accept 一致）。 */
const ALLOWED_EXT = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "png", "jpg", "jpeg", "gif"]
const MAX_MB = 50
/** 附件格式 / 大小違規統一訊息（DM-MSG-DM02-015）。 */
const FILE_MSG = "附件格式不支援或超過大小上限（比照文件上傳）"

const fileExt = (name: string): string => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : "")

/** 廢止申請表單驗證（對齊後端：reason 必填、reviewer 必填、附件選填但須合格式 / 大小）。 */
export const ObsoleteRequestSchema = z.object({
  reason: z.string().trim().min(1, { message: "請填寫廢止原因" }), // DM-MSG-DM02-011
  reviewer_id: z.string().min(1, { message: "請選擇指定審核者" }), // DM-MSG-DM02-014
  file: z
    .instanceof(File)
    .nullable()
    .optional()
    .refine((f) => !f || f.size <= MAX_MB * 1024 * 1024, { message: FILE_MSG })
    .refine((f) => !f || ALLOWED_EXT.includes(fileExt(f.name)), { message: FILE_MSG }), // DM-MSG-DM02-015
})

export type ObsoleteRequestValues = z.infer<typeof ObsoleteRequestSchema>
