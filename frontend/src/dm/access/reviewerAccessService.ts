import { http } from "../../services/http"

/** DM 審核者入口可見性（#250；對齊後端 GET /api/dm/reviewer-access）。 */
export interface DmReviewerAccess {
  can_access: boolean
}

export const dmReviewerAccessApi = {
  /** 是否具 DM_REVIEWER（供側欄決定「簽核中心」是否顯示）。 */
  get: async (): Promise<DmReviewerAccess> => {
    const { data } = await http.get<DmReviewerAccess>("/dm/reviewer-access")
    return data
  },
}
