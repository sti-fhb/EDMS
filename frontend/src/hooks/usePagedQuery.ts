import { useQuery, useQueryClient } from "@tanstack/react-query"
import type { QueryKey } from "@tanstack/react-query"

/** 後端分頁回應格式（對齊 `paginate()` helper）。 */
export interface PageMeta {
  total: number
  page: number
  limit: number
  total_pages: number
}

export interface PagedResult<T> {
  data: T[]
  meta: PageMeta
}

/**
 * 後端分頁查詢。包 `useQuery` + 提供 `invalidate`（重取當前 key）。
 *
 * 禁止各頁裸用 `useQuery` 或於 `useEffect` 內呼叫 axios。
 */
export function usePagedQuery<T>(queryKey: QueryKey, queryFn: () => Promise<PagedResult<T>>) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey, queryFn })

  const invalidate = () => queryClient.invalidateQueries({ queryKey })

  return { data: query.data, isPending: query.isPending, isError: query.isError, invalidate }
}
