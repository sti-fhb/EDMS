import { z } from "zod"

/** 編輯排程：作業名稱與 cron 必填、說明選填。對齊後端 ScheduleUpdate（job_name ≤100、description ≤200、cron_expr ≤50）。
 *  cron 語法之權威檢核在後端 validate_cron（DP_SCHED_002），前端只擋空值與長度。 */
export const ScheduleUpdateSchema = z.object({
  job_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入作業名稱" })
    .max(100, { message: "作業名稱長度不可超過 100 字元" }),
  // 留白轉 null：後端以 null 清空，不存空字串
  description: z
    .string()
    .trim()
    .max(200, { message: "說明長度不可超過 200 字元" })
    .transform((v) => v || null),
  cron_expr: z
    .string()
    .trim()
    .min(1, { message: "請輸入 cron 表達式" })
    .max(50, { message: "cron 表達式長度不可超過 50 字元" }),
  is_enabled: z.boolean(),
})

export type ScheduleUpdateValues = z.infer<typeof ScheduleUpdateSchema>
