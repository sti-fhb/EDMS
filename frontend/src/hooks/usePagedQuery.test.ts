import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { createElement } from "react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { usePagedQuery } from "./usePagedQuery"
import type { PagedResult } from "./usePagedQuery"

interface Item {
  id: string
}

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
  return { queryClient, wrapper }
}

const result: PagedResult<Item> = {
  data: [{ id: "1" }, { id: "2" }],
  meta: { total: 2, page: 1, limit: 10, total_pages: 1 },
}

describe("usePagedQuery", () => {
  it("回傳 queryFn 的分頁結果", async () => {
    const { wrapper } = makeWrapper()
    const queryFn = vi.fn().mockResolvedValue(result)

    const { result: hook } = renderHook(() => usePagedQuery<Item>(["users", "list", { page: 1 }], queryFn), {
      wrapper,
    })

    await waitFor(() => expect(hook.current.isPending).toBe(false))
    expect(hook.current.data).toEqual(result)
    expect(queryFn).toHaveBeenCalledTimes(1)
  })

  it("invalidate 以相同 queryKey 使查詢失效", async () => {
    const { queryClient, wrapper } = makeWrapper()
    const spy = vi.spyOn(queryClient, "invalidateQueries")
    const queryFn = vi.fn().mockResolvedValue(result)
    const key = ["users", "list", { page: 1 }]

    const { result: hook } = renderHook(() => usePagedQuery<Item>(key, queryFn), { wrapper })
    await waitFor(() => expect(hook.current.isPending).toBe(false))

    hook.current.invalidate()

    expect(spy).toHaveBeenCalledWith({ queryKey: key })
  })
})
