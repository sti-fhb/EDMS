/**
 * 稽核代碼 → 中文的查表工具（US10 / #477）。
 *
 * **對照表本身不在前端**——改由 `GET /dp/audit/options` 取得（`useAuditOptions`），本檔只提供
 * 從那份選項查 label 的小工具。
 *
 * #477 之前這裡硬編碼了 `ACTION_LABELS` / `RESULT_LABELS`，另有一份 `FUNC_OPTIONS` 寫在
 * `AuditPage.tsx`，三者都靠註解要求與後端「手動同步」。結果是：兩邊確實同步了，但同步的是
 * **同一份過時清單**——少了 13 個功能碼（ET 整組缺席，其中 `ET-COURSE` 是全表第二大），
 * 而且下拉提供的「匯出」在後端值域裡根本不存在、選了就 422。雙寫的失效是靜默的，
 * 沒有任何測試會因為「新模組寫了稽核卻沒人補清單」而變紅。
 *
 * 送給 API 的值一律維持英文碼，中文僅用於畫面呈現。
 * 注意：稽核之失敗碼為 `FAIL`，與排程的 `FAILED` 不同。
 */

import type { AuditOption } from "./auditService"

/**
 * 從選項清單查中文；查不到（含選項尚未載入）回原碼。
 *
 * 回原碼而非空字串是刻意的——使用者至少看得到 `ET-COURSE` 這種可辨識的值並能回報，
 * 空白則會讓人以為那一欄沒有資料。
 */
export function labelOf(options: AuditOption[], code: string): string {
  return options.find((o) => o.value === code)?.label ?? code
}
