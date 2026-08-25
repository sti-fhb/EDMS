import { z } from "zod"

// 近似值：僅供 client-side 提前擋錯改善 UX，權威檢核仍在後端 file_store（DM_FILE_MAX_MB / DM_FILE_TYPES，
// 管理者可於 DM03 調整）。若後端參數調整，此處需同步，否則會與後端行為落差（過嚴擋合法檔 / 過寬送出才被拒）。
/** 廢止附件格式白名單（比照文件上傳；對齊後端 DM_FILE_TYPES 預設 / wireframe accept）。 */
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
