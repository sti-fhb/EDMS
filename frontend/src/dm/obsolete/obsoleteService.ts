import type { ObsoleteAccess, ObsoleteDocItem, ObsoleteFilters } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"
import { http } from "../../services/http"

export interface ObsoleteSearchParams extends ObsoleteFilters {
  page: number
  limit: number
}

/** 空字串條件轉 undefined（不送出空過濾）。 */
function filterParams(f: ObsoleteFilters) {
  return {
    keyword: f.keyword || undefined,
    category: f.category || undefined,
    date_from: f.dateFrom || undefined,
    date_to: f.dateTo || undefined,
  }
}

/** 已廢止文件查詢 API（唯讀，DM_ADMIN；後端硬閘擋直連）。 */
export const obsoleteApi = {
  /** 多條件查詢已廢止文件（後端分頁、廢止時間 DESC）。 */
  search: async (p: ObsoleteSearchParams): Promise<PagedResult<ObsoleteDocItem>> => {
    const { data } = await http.get<PagedResult<ObsoleteDocItem>>("/dm/obsolete-archive/documents", {
      params: { ...filterParams(p), page: p.page, limit: p.limit },
    })
    return data
  },

  /** 入口可見性（供側欄逐項閘；具 DM_ADMIN 才顯示）。 */
  getAccess: async (): Promise<ObsoleteAccess> => {
    const { data } = await http.get<ObsoleteAccess>("/dm/obsolete-archive/access")
    return data
  },

  /** 匯出當前查詢結果為 CSV blob。 */
  exportCsvBlob: async (f: ObsoleteFilters): Promise<Blob> => {
    const { data } = await http.get<Blob>("/dm/obsolete-archive/documents/export", {
      params: filterParams(f),
      responseType: "blob",
    })
    return data
  },
}

/** 匯出當前查詢結果 CSV → 觸發瀏覽器下載。 */
export async function downloadObsoleteCsv(f: ObsoleteFilters): Promise<void> {
  const blob = await obsoleteApi.exportCsvBlob(f)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "obsolete-documents.csv"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
