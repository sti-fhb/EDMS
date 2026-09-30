import { useQuery } from "@tanstack/react-query"

import { etDashboardApi } from "./dashboardService"
import { QUERY_KEYS } from "../../constants/queryKeys"

/**
 * 首頁三張卡（#453）。
 *
 * ⚠️ 本 hook **只在確定具任一 ET 角色時才呼叫**（`enabled`）——端點對無 ET 角色者回
 * 403，登入後先打一次再被擋等於每位純 DM 使用者的首頁都固定吃一個 403。
 */
export function useEtDashboard(enabled: boolean) {
  return useQuery({ queryKey: QUERY_KEYS.etDashboard.get(), queryFn: etDashboardApi.get, enabled })
}
