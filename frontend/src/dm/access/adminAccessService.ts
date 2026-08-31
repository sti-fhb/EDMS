import { http } from "../../services/http"

/** DM 管理者入口可見性（共用；對齊後端 GET /api/dm/admin-access）。 */
export interface DmAdminAccess {
  can_access: boolean
}

export const dmAdminAccessApi = {
  /** 是否具 DM_ADMIN（供側欄逐項閘 US10 已廢止 / US11 變更歷程 / US13 KPI 共用）。 */
  get: async (): Promise<DmAdminAccess> => {
    const { data } = await http.get<DmAdminAccess>("/dm/admin-access")
    return data
  },
}
