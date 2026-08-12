import type { ControlledOption, DocumentListItem, LibraryFilters } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"
import { http } from "../../services/http"

export interface SearchParams extends LibraryFilters {
  page: number
  limit: number
}

/** 文件庫與檢索 API（唯讀）。 */
export const libraryApi = {
  /** 多條件搜尋已發布目前版本（後端分頁；閱覽者由後端套可見性）。 */
  search: async (p: SearchParams): Promise<PagedResult<DocumentListItem>> => {
    const { data } = await http.get<PagedResult<DocumentListItem>>("/dm/library/documents", {
      params: {
        keyword: p.keyword || undefined,
        category: p.category || undefined,
        author: p.author || undefined,
        tag_ids: p.tagIds.length > 0 ? p.tagIds : undefined,
        func_code: p.funcCode || undefined,
        date_from: p.dateFrom || undefined,
        date_to: p.dateTo || undefined,
        page: p.page,
        limit: p.limit,
      },
      // 陣列參數用重複格式 tag_ids=6&tag_ids=7（indexes:null），對齊 FastAPI list[int]=Query()；
      // 預設 axios 會序列化成 tag_ids[]=6 帶括號，FastAPI 不認 → 過濾失效。
      paramsSerializer: { indexes: null },
    })
    return data
  },

  /** 系統操作手冊檢索之 func_name 下拉（啟用中）。 */
  funcOptions: async (): Promise<ControlledOption[]> => {
    const { data } = await http.get<ControlledOption[]>("/dm/library/func-options")
    return data
  },

  /** 檢索標籤下拉（啟用中、含所屬組；不含可見對象）。 */
  retrievalTags: async (): Promise<ControlledOption[]> => {
    const { data } = await http.get<ControlledOption[]>("/dm/library/retrieval-tags")
    return data
  },

  /** 當前使用者文件庫操作能力（can_create：是否顯示新增文件入口）。 */
  capabilities: async (): Promise<{ can_create: boolean }> => {
    const { data } = await http.get<{ can_create: boolean }>("/dm/library/capabilities")
    return data
  },
}