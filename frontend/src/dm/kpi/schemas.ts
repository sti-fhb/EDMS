/** 閱讀統計 KPI（US13 / UCDM13 / DM10）型別（對齊後端 app/dm/kpi/schemas.py）。 */

import type { PagedResult } from "../../hooks/usePagedQuery"

/** 逐文件閱讀 KPI 列。rate 為 null＝應看=0（無對應閱覽者），前端顯示「—」且不計整體平均。 */
export interface KpiDocItem {
  doc_id: string
  doc_name: string
  category_code: string
  category_name: string | null
  current_version_no: string | null
  should_see: number
  seen: number
  unseen: number
  rate: number | null // 0~1
}

/** 頂部統計卡（整體平均排除應看=0 文件）。 */
export interface KpiSummary {
  total_docs: number
  overall_rate: number | null
  below_50_count: number
}

/** KPI 儀表板回應：逐文件清單（分頁）+ 統計卡摘要。 */
export type KpiListResponse = PagedResult<KpiDocItem> & { summary: KpiSummary }

/** 查詢條件（關鍵字＝文件名；分類）。 */
export interface KpiFilters {
  keyword: string
  category: string // '' = 全部
}

export const EMPTY_KPI_FILTERS: KpiFilters = {
  keyword: "",
  category: "",
}
