import type { ZodError } from "zod"

/**
 * 將 Zod 驗證失敗的 error 轉為 `{ 欄位: 訊息 }`，對應 MUI TextField 的 error + helperText。
 * 同欄位取第一則訊息；無 path 的頂層 refine 錯誤歸於 `_form`。
 * 用法：`const r = schema.safeParse(data); const errors = getFieldErrors(r.success ? null : r.error)`
 */
export function getFieldErrors(error: ZodError | null): Record<string, string> {
  if (error === null) return {}
  const result: Record<string, string> = {}
  for (const issue of error.issues) {
    const key = issue.path.map(String).join(".") || "_form"
    if (!(key in result)) result[key] = issue.message
  }
  return result
}
