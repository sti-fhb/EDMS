import { useQuery } from "@tanstack/react-query"

import { dmAdminAccessApi } from "./adminAccessService"

/**
 * DM 管理者入口可見性（具 DM_ADMIN）。供側欄逐項閘 admin-only 項（US10 已廢止 / US11 變更歷程 /
 * US13 KPI 共用；US11 SA 裁示 Q1=A' 收斂）。`enabled` 於側欄僅在「具任一 DM 角色」時開啟，
 * 避免非 DM 使用者觸發查詢；頁面內預設啟用（用於進頁權限先判）。
 */
export function useDmAdminAccess(enabled = true) {
  return useQuery({
    queryKey: ["dm", "admin-access"],
    queryFn: dmAdminAccessApi.get,
    enabled,
  })
}
