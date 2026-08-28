/** 已廢止文件查詢（US10 / UCDM08 / DM06）型別（對齊後端 app/dm/obsolete_archive/schemas.py）。 */

/** 已廢止文件清單列（含末版版號 + 廢止脈絡）。原作者採末版〔在架版〕作者（SA 裁示 Q2=B）。 */
export interface ObsoleteDocItem {
  doc_id: string
  doc_name: string
  latest_version_no: string | null
  category_code: string
  category_name: string
  author_id: string | null
  author_name: string | null
  obsolete_date: string | null
  applicant_id: string | null
  applicant_name: string | null
  approver_id: string | null
  approver_name: string | null
  obsolete_reason: string | null
}

/** DM06 入口可見性（供側欄逐項閘）。 */
export interface ObsoleteAccess {
  can_access: boolean
}

/** 查詢條件（關鍵字＝文件名 / 廢止原因；分類；廢止日期區間）。 */
export interface ObsoleteFilters {
  keyword: string
  category: string // '' = 全部
  dateFrom: string
  dateTo: string
}

export const EMPTY_OBSOLETE_FILTERS: ObsoleteFilters = {
  keyword: "",
  category: "",
  dateFrom: "",
  dateTo: "",
}
