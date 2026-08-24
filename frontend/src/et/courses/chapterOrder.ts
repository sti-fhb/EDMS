/**
 * 章節順序計算（ET02 拖拉重排）。
 *
 * 獨立成模組而非留在 `ChapterSection.tsx`：一來元件檔匯出非元件會破壞 Fast Refresh
 * （`react-refresh/only-export-components`），二來 `@dnd-kit` 的拖曳與鍵盤感測都需要
 * 元素的版面矩形，jsdom 中所有 rect 皆為 0、互動本身在單元測試環境驗不了。順序計算
 * 是這裡唯一會出錯的邏輯，抽出來即可完整覆蓋；拖曳接線本身留給 E2E / 人工驗證。
 */

/**
 * 把 `activeId` 移到 `overId` 的位置，回傳**完整**的新順序陣列。
 *
 * 回傳完整陣列而非相對位移，對齊後端 `ensure_reorder_complete` 的契約——
 * 相對移動在並行編輯時會疊加出非預期結果。
 *
 * @returns 新順序；`activeId` 或 `overId` 不在清單中時回 `null`（不動作）。
 */
export function moveId(ids: number[], activeId: number, overId: number): number[] | null {
  const from = ids.indexOf(activeId)
  const to = ids.indexOf(overId)
  if (from < 0 || to < 0) return null
  const next = [...ids]
  next.splice(to, 0, ...next.splice(from, 1))
  return next
}
