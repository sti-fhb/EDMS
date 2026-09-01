import { changeLogApi } from "./changeLogService"
import type { ChangeLogSearchParams } from "./changeLogService"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 文件變更歷程查詢（後端分頁）。`enabled`：僅在確認具管理者權限後才發查詢（避免非管理者觸發 403 噪音）。 */
export function useChangeLogSearch(params: ChangeLogSearchParams, options?: { enabled?: boolean }) {
  return usePagedQuery(["dm-change-log", "entries", params], () => changeLogApi.search(params), options)
}
