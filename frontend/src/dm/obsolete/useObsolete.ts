import { useQuery } from "@tanstack/react-query"

import { obsoleteApi } from "./obsoleteService"
import type { ObsoleteSearchParams } from "./obsoleteService"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 已廢止文件查詢（後端分頁）。`enabled`：僅在確認具管理者權限後才發查詢（避免非管理者觸發 403 噪音）。 */
export function useObsoleteSearch(params: ObsoleteSearchParams, options?: { enabled?: boolean }) {
  return usePagedQuery(["dm-obsolete-archive", "documents", params], () => obsoleteApi.search(params), options)
}

/**
 * DM06 入口可見性（具 DM_ADMIN）。供側欄閘「已廢止文件查詢」單項（SA 裁示 Q1=A，鏡像 US9 個人專區）。
 * `enabled` 於側欄僅在「具任一 DM 角色」時開啟，避免非 DM 使用者觸發查詢。
 */
export function useObsoleteAccess(enabled = true) {
  return useQuery({
    queryKey: ["dm-obsolete-archive", "access"],
    queryFn: obsoleteApi.getAccess,
    enabled,
  })
}
