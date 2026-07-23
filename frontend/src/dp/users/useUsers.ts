import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { useCrudForm } from "../../hooks/useCrudForm"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { usersApi } from "./usersService"
import type { UserCreatePayload, UserRow, UserUpdatePayload } from "./usersService"

const DEFAULT_LIMIT = 20

/** 使用者管理頁狀態與操作（查詢 / 建立 / 停用 / 啟用 / 解鎖 / 編輯）。 */
export function useUsers() {
  const { message, confirm } = useNotification()
  const queryClient = useQueryClient()
  const { formVisible, editingRecord, saving, setSaving, openCreate, openEdit, closeForm } = useCrudForm<UserRow>()

  // 已送出的查詢條件（與輸入分離：按「查詢」才套用）
  const [query, setQuery] = useState({ q: "", status: "", page: 1, limit: DEFAULT_LIMIT })

  const { data, isPending, invalidate } = usePagedQuery(QUERY_KEYS.users.list(query), () =>
    usersApi.list({
      q: query.q || undefined,
      status: query.status || undefined,
      page: query.page,
      limit: query.limit,
    }),
  )

  const search = useCallback((q: string, status: string) => {
    setQuery((prev) => ({ ...prev, q, status, page: 1 }))
  }, [])

  const setPage = useCallback((page: number) => setQuery((prev) => ({ ...prev, page })), [])

  const handleSave = useCallback(
    async (values: UserCreatePayload | UserUpdatePayload) => {
      setSaving(true)
      try {
        if (editingRecord) {
          await usersApi.updateName(editingRecord.user_id, values as UserUpdatePayload)
          message.success("已更新姓名")
        } else {
          await usersApi.create(values as UserCreatePayload)
          message.success("邀請信已寄出，使用者需經連結設定密碼後啟用")
        }
        closeForm()
        // 以 ["users"] 前綴一併失效清單與待啟用邀請 cache：建立邀請成功後，即使停在「待啟用邀請」頁籤也即時刷新
        queryClient.invalidateQueries({ queryKey: ["users"] })
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      } finally {
        setSaving(false)
      }
    },
    [editingRecord, message, closeForm, invalidate, setSaving],
  )

  const disableUser = useCallback(
    (row: UserRow) => {
      confirm({
        title: "停用帳號",
        content: `確定停用「${row.user_name}」的帳號？停用後 ET / DM 兩端將同步失效。`,
        danger: true,
        okText: "確定停用",
        onOk: async () => {
          try {
            await usersApi.setStatus(row.user_id, "disable")
            message.success("帳號已停用")
            invalidate()
          } catch (err) {
            // 顯示錯誤並 rethrow：NotificationContext 據此保留對話框、解除 loading 供重試
            message.error(toApiError(err).errorMessage)
            throw err
          }
        },
      })
    },
    [confirm, message, invalidate],
  )

  const enableUser = useCallback(
    async (row: UserRow) => {
      try {
        await usersApi.setStatus(row.user_id, "enable")
        message.success("帳號已啟用")
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      }
    },
    [message, invalidate],
  )

  const unlockUser = useCallback(
    async (row: UserRow) => {
      try {
        await usersApi.unlock(row.user_id)
        message.success("帳號已解鎖")
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      }
    },
    [message, invalidate],
  )

  return {
    items: data?.data ?? [],
    total: data?.meta?.total ?? 0,
    loading: isPending,
    page: query.page,
    setPage,
    search,
    formVisible,
    editingRecord,
    saving,
    openCreate,
    openEdit,
    closeForm,
    handleSave,
    disableUser,
    enableUser,
    unlockUser,
  }
}
