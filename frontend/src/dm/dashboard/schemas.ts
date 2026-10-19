/** 系統儀表板（US7 / DM00）型別（對齊後端 app/dm/dashboard/schemas.py）。 */

export interface CategoryStat {
  category_code: string
  category_name: string
  count: number
}

export interface DashboardStats {
  items: CategoryStat[]
  total: number
}

export interface AnnouncementItem {
  doc_id: string
  doc_name: string
  category_code: string // 後端仍回傳（對外相容），但無消費者——⚠️ 與上方 CategoryStat 的同名欄位無關
  category_name: string // 分類中文名稱，查表取目前值——公告列顯示此欄（#735）
  version_no: string
  change_summary: string | null
  published_date: string
  author_name: string | null
  kind: string // NEW（新增）/ NEW_VERSION（新版本）
}

/** 類型 badge 顯示名。 */
export const KIND_LABELS: Record<string, string> = {
  NEW: "新增",
  NEW_VERSION: "新版本",
}
