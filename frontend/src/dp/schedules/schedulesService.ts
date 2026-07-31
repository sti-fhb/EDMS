import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"

/** 排程 job（對齊後端 ScheduleResponse）。 */
export interface ScheduleRow {
  job_id: string
  job_name: string
  module: string
  cron_expr: string
  is_enabled: boolean
  last_run_date: string | null
  last_run_status: string | null
}

/** 排程執行歷程（對齊後端 ScheduleLogResponse）。 */
export interface ScheduleLogRow {
  log_id: number
  job_id: string
  start_date: string
  end_date: string | null
  status: string
  error_msg: string | null
}

/** 排程總覽 API（US11，唯讀）。 */
export const schedulesApi = {
  async list(): Promise<ScheduleRow[]> {
    const { data } = await http.get<ScheduleRow[]>("/dp/schedules")
    return data
  },
  async logs(jobId: string, params: { page: number; limit: number }): Promise<PagedResult<ScheduleLogRow>> {
    const { data } = await http.get<PagedResult<ScheduleLogRow>>(`/dp/schedules/${jobId}/logs`, { params })
    return data
  },
}
