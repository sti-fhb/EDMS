import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"

/** 單筆操作記錄（對齊後端 AuditLogResponse）。before/after 為 JSON 字串，前端 parse 後呈現。 */
export interface AuditLogRow {
  log_id: number
  created_date: string
  operator_id: string
  operator_name: string | null
  module: string
  func_name: string
  action_type: string
  result: string
  target_id: string | null
  source_ip: string | null
  description: string | null
  before_value: string | null
  after_value: string | null
}

/** 查詢條件（空字串欄位於送出前轉為 undefined，不帶入 query string）。 */
export interface AuditFilterParams {
  operator?: string
  module?: string
  action_type?: string
  result?: string
  date_from?: string
  date_to?: string
}

export interface AuditQueryParams extends AuditFilterParams {
  page: number
  limit: number
}

/** 操作記錄查詢 API（US10，唯讀）。路徑相對於 baseURL（/api）。 */
export const auditApi = {
  async list(params: AuditQueryParams): Promise<PagedResult<AuditLogRow>> {
    const { data } = await http.get<PagedResult<AuditLogRow>>("/dp/audit/logs", { params })
    return data
  },
  /** 依查詢條件全量匯出 CSV；以 blob 取回（http 攔截器帶 Authorization）。 */
  async exportCsv(params: AuditFilterParams): Promise<Blob> {
    const { data } = await http.get("/dp/audit/logs/export", { params, responseType: "blob" })
    return data as Blob
  },
}