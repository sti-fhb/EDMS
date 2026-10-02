/** 文件庫與檢索（US3 / DM01）型別（對齊後端 app/dm/library/schemas.py）。 */

/** 文件庫清單列（已發布目前版本）。 */
export interface DocumentListItem {
  doc_id: string
  doc_name: string
  category_code: string
  category_name: string
  published_date: string | null
  author_id: string
  author_name: string | null
  func_code: string | null
  func_name: string | null
  tags: string[] // 檢索標籤名稱（灰字頓號呈現；不含可見對象）
}

/** 受控清單下拉選項（func_name / 檢索標籤）。 */
export interface ControlledOption {
  code: string
  name: string
  group_code: string | null // 檢索標籤所屬組（MODULE / NATURE / LEGAL），供前端分組
}

/** 文件庫搜尋條件。 */
export interface LibraryFilters {
  keyword: string
  category: string // '' = 全部
  author: string
  tagIds: number[]
  funcCode: string // '' = 全部（僅 MANUAL 分類使用）
  dateFrom: string
  dateTo: string
}

export const EMPTY_LIBRARY_FILTERS: LibraryFilters = {
  keyword: "",
  category: "",
  author: "",
  tagIds: [],
  funcCode: "",
  dateFrom: "",
  dateTo: "",
}

/**
 * 系統操作手冊分類代碼（選此分類才顯示關聯作業項目 func_name 下拉）。
 *
 * ⚠️ 這是**行為分支的 key**，不是清單資料。分類清單本身請用 `useCategoryOptions()` 向後端取
 * （`DM_CATEGORY` 可由 DP 後台新增 / 改名 / 停用，寫死會與後台脫鉤——#483 第 1 項）。
 */
export const MANUAL_CATEGORY = "MANUAL"