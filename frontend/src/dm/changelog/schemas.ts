/** 文件變更歷程查詢（US11 / UCDM10 / DM08）型別（對齊後端 app/dm/change_log/schemas.py）。 */

export type ChangeLogOperation = "PUBLISH" | "OBSOLETE"

/** 變更歷程清單列（發布 / 廢止事件）。備註：發布＝變更摘要、廢止＝廢止原因。 */
export interface ChangeLogEntry {
  change_log_id: number
  operation_time: string | null
  operation: ChangeLogOperation
  applicant_id: string
  applicant_name: string | null
  approver_id: string
  approver_name: string | null
  doc_id: string
  doc_name: string
  version_no: string | null
  note: string | null
}

/** 查詢條件（申請人/核准人＝帳號或姓名；操作類型；日期區間）。 */
export interface ChangeLogFilters {
  keyword: string // 申請人 / 核准人（帳號或姓名）
  operation: string // '' = 全部；'PUBLISH' | 'OBSOLETE'
  dateFrom: string
  dateTo: string
}

export const EMPTY_CHANGE_LOG_FILTERS: ChangeLogFilters = {
  keyword: "",
  operation: "",
  dateFrom: "",
  dateTo: "",
}
