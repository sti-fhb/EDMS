import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { usersApi } from "./usersService"
import type { InviteRow } from "./usersService"

const DEFAULT_LIMIT = 20

/** 待啟用邀請頁籤狀態與操作（查詢 / 重寄 / 取消）。 */
export function useInvites(enabled: boolean) {
  const { message, confirm } = useNotification()
  const [query, setQuery] = useState({ q: "", page: 1, limit: DEFAULT_LIMIT })

  const { data, isPending, invalidate } = usePagedQuery(
    QUERY_KEYS.users.invites(query),
    () => usersApi.listInvites({ q: query.q || undefined, page: query.page, limit: query.limit }),
    { enabled },
  )

  const search = useCallback((q: string) => setQuery((prev) => ({ ...prev, q, page: 1 })), [])
  const setPage = useCallback((page: number) => setQuery((prev) => ({ ...prev, page })), [])

  const resendInvite = useCallback(
    async (row: InviteRow) => {
      try {
        await usersApi.resendInvite(row.res_id)
        message.success("邀請信已重寄")
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      }
    },
    [message, invalidate],
  )

  const cancelInvite = useCallback(
    (row: InviteRow) => {
      confirm({
        title: "取消邀請",
        content: `確定取消「${row.user_name}」（${row.email}）的邀請？`,
        danger: true,
        okText: "確定取消",
        onOk: async () => {
          try {
            await usersApi.cancelInvite(row.res_id)
            message.success("已取消邀請")
            invalidate()
          } catch (err) {
            message.error(toApiError(err).errorMessage)
            throw err
          }
        },
      })
    },
    [confirm, message, invalidate],
  )

  return {
    items: data?.data ?? [],
    total: data?.meta?.total ?? 0,
    loading: isPending,
    page: query.page,
    setPage,
    search,
    resendInvite,
    cancelInvite,
    invalidate,
  }
}