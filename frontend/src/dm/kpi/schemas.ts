/** 閱讀統計 KPI（US13 / UCDM13 / DM06）型別（對齊後端 app/dm/kpi/schemas.py）。 */

import type { PagedResult } from "../../hooks/usePagedQuery"

/**
 * 單一可見對象組之完成度。
 *
 * ⚠️ 逐組 `should_see` 之加總會 ≥ 文件的 `should_see`：一人可同時符合同一份文件的多組
 * （身兼兩職），各組分母都含他、文件總計去重。畫面必須標註，否則讀者會判定成算錯。
 */
export interface KpiAudienceGroup {
  label: string // 「全體」／職位名／「單位．職位」
  should_see: number
  seen: number
  unseen: number
  rate: number | null // 該組應看=0 → null（不是 0%）
}

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
  groups: KpiAudienceGroup[]
}

/**
 * 訓練教材清單列——**刻意不含任何閱讀統計欄位**。
 *
 * ET 代學員取檔不寫 `DM_DOC_READ`（後端 `app/et/common/dm_client.py` D-2），於此計算
 * 閱讀率會固定低報。給數字比不給更糟，因為它看起來有權威性。
 */
export interface KpiTrainingDoc {
  doc_id: string
  doc_name: string
  category_name: string | null
  current_version_no: string | null
}

/** 頂部統計卡（整體平均排除應看=0 文件）。 */
export interface KpiSummary {
  total_docs: number // 統計母體文件數（不含訓練教材）
  rated_docs: number // 其中應看>0、可計算閱讀率者——below_50_count 的分母
  overall_rate: number | null
  below_50_count: number
}

/** KPI 儀表板回應：逐文件清單（分頁）+ 統計卡摘要 + 訓練教材清單（不分頁、有上限）。 */
export type KpiListResponse = PagedResult<KpiDocItem> & {
  summary: KpiSummary
  training_docs: KpiTrainingDoc[]
  training_total: number
}

/** 查詢條件（關鍵字＝文件名；分類）。 */
export interface KpiFilters {
  keyword: string
  category: string // '' = 全部
}

export const EMPTY_KPI_FILTERS: KpiFilters = {
  keyword: "",
  category: "",
}
