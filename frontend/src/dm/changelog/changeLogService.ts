import type { ChangeLogEntry, ChangeLogFilters } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"
import { http } from "../../services/http"

export interface ChangeLogSearchParams extends ChangeLogFilters {
  page: number
  limit: number
}

/** 空字串條件轉 undefined（不送出空過濾）。 */
function filterParams(f: ChangeLogFilters) {
  return {
    keyword: f.keyword || undefined,
    operation: f.operation || undefined,
    date_from: f.dateFrom || undefined,
    date_to: f.dateTo || undefined,
  }
}

/** 文件變更歷程查詢 API（唯讀，DM_ADMIN；後端硬閘擋直連）。 */
export const changeLogApi = {
  /** 多條件查詢變更歷程（後端分頁、時間 DESC）。 */
  search: async (p: ChangeLogSearchParams): Promise<PagedResult<ChangeLogEntry>> => {
    const { data } = await http.get<PagedResult<ChangeLogEntry>>("/dm/change-log/entries", {
      params: { ...filterParams(p), page: p.page, limit: p.limit },
    })
    return data
  },

  /** 匯出當前查詢結果為 CSV blob。 */
  exportCsvBlob: async (f: ChangeLogFilters): Promise<Blob> => {
    const { data } = await http.get<Blob>("/dm/change-log/entries/export", {
      params: filterParams(f),
      responseType: "blob",
    })
    return data
  },
}

/** 匯出當前查詢結果 CSV → 觸發瀏覽器下載。 */
export async function downloadChangeLogCsv(f: ChangeLogFilters): Promise<void> {
  const blob = await changeLogApi.exportCsvBlob(f)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "change-log.csv"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
