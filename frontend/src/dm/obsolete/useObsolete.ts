import { useQuery } from "@tanstack/react-query"

import { obsoleteApi } from "./obsoleteService"
import type { ObsoleteSearchParams } from "./obsoleteService"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 已廢止文件查詢（後端分頁）。 */
export function useObsoleteSearch(params: ObsoleteSearchParams) {
  return usePagedQuery(["dm-obsolete-archive", "documents", params], () => obsoleteApi.search(params))
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
