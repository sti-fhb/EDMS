/**
 * DM 檢索標籤組代碼 → 畫面顯示名稱。
 *
 * 供 DM01 文件庫與 DM08 新增 / 編輯文件的檢索標籤下拉做 `groupBy` 分組標題。
 * 兩個畫面原本各寫死一份內容相同的對照表（#711 前），只改一處的症狀是**其中一個畫面
 * 顯示通稱「標籤」而非組名**——畫面不會壞、測試也不會紅，只有肉眼看得出來。故收斂為一份。
 *
 * ⚠️ **與後端是前後端雙寫**：組的資料在 `DM_TAG_GROUP`，說明文字在後端
 * `app/dm/catalog/adapter.py` 的 `_TAG_GROUP_DESCRIPTIONS`。新增一個標籤組時
 * **三處都要改**（seed migration、後端說明、本檔），沒有任何自動化能擋住漏改——
 * 後端有測試守住它那半（`test_每個標籤組都有說明文字`），但它看不到前端。
 *
 * ⛔ 不要在頁面裡再自己寫一份對照表，請 import 本檔。
 */
export const DM_TAG_GROUP_LABELS: Record<string, string> = {
  MODULE: "適用模組",
  NATURE: "文件性質",
  LEGAL: "法規關聯",
  OTHER: "其他",
}

/**
 * 取標籤組的顯示名稱；查無對照（含 null / undefined）時退回通稱「標籤」。
 *
 * 退回通稱而非留空，是因為 `groupBy` 的回傳值直接當分組標題用——給空字串會出現
 * 一個沒有標題的分組，比起寫「標籤」更難看懂。
 */
export function dmTagGroupLabel(groupCode: string | null | undefined): string {
  return DM_TAG_GROUP_LABELS[groupCode ?? ""] ?? "標籤"
}
