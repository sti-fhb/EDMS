import { useQuery } from "@tanstack/react-query"

import { QUERY_KEYS } from "../constants/queryKeys"
import { http } from "../services/http"

/** 單一模組於目前使用者之權限狀態（是否具任一角色）。 */
export interface ModuleRoleStatus {
  has_role: boolean
}

/** 入口頁 / 側欄用模組摘要（對應後端 GET /api/dp/user/module-summary）。 */
export interface ModuleSummary {
  et: ModuleRoleStatus
  dm: ModuleRoleStatus
}

/** 查目前使用者各模組是否具權限，供側欄決定模組群組顯示與否（US1，§4 has_any_role 聚合）。 */
export function useModuleSummary() {
  return useQuery({
    queryKey: QUERY_KEYS.moduleSummary.get(),
    queryFn: async (): Promise<ModuleSummary> => {
      const { data } = await http.get<ModuleSummary>("/dp/user/module-summary")
      return data
    },
  })
}