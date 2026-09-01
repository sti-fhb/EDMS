import { obsoleteApi } from "./obsoleteService"
import type { ObsoleteSearchParams } from "./obsoleteService"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 已廢止文件查詢（後端分頁）。`enabled`：僅在確認具管理者權限後才發查詢（避免非管理者觸發 403 噪音）。 */
export function useObsoleteSearch(params: ObsoleteSearchParams, options?: { enabled?: boolean }) {
  return usePagedQuery(["dm-obsolete-archive", "documents", params], () => obsoleteApi.search(params), options)
}

// 入口可見性改用共用 useDmAdminAccess（`../access/useDmAdminAccess`；US11 A' 收斂）。
