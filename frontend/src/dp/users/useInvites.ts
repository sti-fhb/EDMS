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
        await usersApi.resendInvite(row.invite_id)
        message.success("邀請信已重寄")
        invalidate()
      } catch (err) {
        // 冷卻中（429 帶 retry_after，#72）→ 以剩餘時間提示，取代籠統的「操作過於頻繁」
        const e = toApiError(err)
        if (e.status === 429 && e.retryAfter) {
          message.error(`此邀請剛重寄過，請於約 ${Math.ceil(e.retryAfter / 60)} 分鐘後再試`)
        } else {
          message.error(e.errorMessage)
        }
      }
    },
    [message, invalidate],
  )

  const cancelInvite = useCallback(
    (row: InviteRow) => {
      confirm({
        title: "取消邀請",
        content: `確定取消「${row.user_name}」（${row.email}）的邀請？`,
        okText: "確定取消",
        onOk: async () => {
          try {
            await usersApi.cancelInvite(row.invite_id)
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