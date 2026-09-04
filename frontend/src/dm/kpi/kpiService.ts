import type { KpiFilters, KpiListResponse } from "./schemas"
import { http } from "../../services/http"

export interface KpiSearchParams extends KpiFilters {
  page: number
  limit: number
}

/** 空字串條件轉 undefined（不送出空過濾）。 */
function filterParams(f: KpiFilters) {
  return {
    keyword: f.keyword || undefined,
    category: f.category || undefined,
  }
}

/** 閱讀統計 KPI API（唯讀，DM_ADMIN；後端硬閘擋直連）。 */
export const kpiApi = {
  /** 逐文件 KPI（後端分頁）+ 統計卡摘要。 */
  search: async (p: KpiSearchParams): Promise<KpiListResponse> => {
    const { data } = await http.get<KpiListResponse>("/dm/kpi/documents", {
      params: { ...filterParams(p), page: p.page, limit: p.limit },
    })
    return data
  },

  /** 匯出當前查詢結果為 CSV blob。 */
  exportCsvBlob: async (f: KpiFilters): Promise<Blob> => {
    const { data } = await http.get<Blob>("/dm/kpi/documents/export", {
      params: filterParams(f),
      responseType: "blob",
    })
    return data
  },
}

/** 匯出當前查詢結果 CSV → 觸發瀏覽器下載。 */
export async function downloadKpiCsv(f: KpiFilters): Promise<void> {
  const blob = await kpiApi.exportCsvBlob(f)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "kpi-reading-stats.csv"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
