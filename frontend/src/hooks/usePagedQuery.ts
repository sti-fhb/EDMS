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
export function usePagedQuery<T>(
  queryKey: QueryKey,
  queryFn: () => Promise<PagedResult<T>>,
  options?: { enabled?: boolean },
) {
  const queryClient = useQueryClient()
  const enabled = options?.enabled ?? true
  const query = useQuery({ queryKey, queryFn, enabled })

  const invalidate = () => queryClient.invalidateQueries({ queryKey })

  // enabled=false 時 useQuery 仍為 pending；以 enabled 收斂 loading，避免未啟用頁籤顯示載入中
  return { data: query.data, isPending: enabled && query.isPending, isError: query.isError, invalidate }
}
