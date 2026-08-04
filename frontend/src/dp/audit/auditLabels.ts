/**
 * 稽核代碼 → 中文對照（US10）。
 *
 * 代碼為後端寫死之 enum（`ACTION_TYPE` 種子清單不納參數維護頁，見 #68），故於前端硬編碼；
 * 送給 API 的值一律維持英文碼，中文僅用於畫面呈現。
 * 注意：稽核之失敗碼為 `FAIL`，與排程的 `FAILED` 不同，兩處對照表不共用。
 *
 * ⚠️ 同一份對照另存於後端 `app/dp/audit/query_service.py` 的 `_ACTION_LABELS` / `_RESULT_LABELS`
 * （供 CSV 匯出）。新增或修改 `action_type` / `result` 列舉值時，兩邊必須同步，
 * 否則畫面與匯出檔會出現一邊中文、一邊原碼的不一致（未知碼 fallback 不會報錯，只會靜默不一致）。
 */

const ACTION_LABELS: Record<string, string> = {
  LOGIN: "登入",
  LOGOUT: "登出",
  CREATE: "新增",
  UPDATE: "修改",
  DELETE: "刪除",
}

const RESULT_LABELS: Record<string, string> = {
  SUCCESS: "成功",
  FAIL: "失敗",
}

/** 下拉選項（value=英文碼、label=中文）；「全部」以 sentinel 呈現，同 FUNC_OPTIONS。 */
export const ACTION_OPTIONS: { value: string; label: string }[] = [
  { value: "全部", label: "全部" },
  ...Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label })),
]

export const RESULT_OPTIONS: { value: string; label: string }[] = [
  { value: "全部", label: "全部" },
  ...Object.entries(RESULT_LABELS).map(([value, label]) => ({ value, label })),
]

/** 操作類別代碼 → 中文；未知碼原樣回傳。 */
export function actionLabel(code: string): string {
  return ACTION_LABELS[code] ?? code
}

/** 執行結果代碼 → 中文；未知碼原樣回傳。 */
export function resultLabel(code: string): string {
  return RESULT_LABELS[code] ?? code
}
