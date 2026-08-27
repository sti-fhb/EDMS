import type { ActivityResponse, DraftItem, PersonalAccess, WithdrawResult } from "./schemas"
import { http } from "../../services/http"

/** 個人專區 API（US9 / DM07）。 */
export const personalApi = {
  listDrafts: async (): Promise<DraftItem[]> => {
    const { data } = await http.get<DraftItem[]>("/dm/personal/drafts")
    return data
  },

  deleteDraft: async (versionId: number): Promise<void> => {
    await http.delete(`/dm/personal/drafts/${versionId}`)
  },

  getActivity: async (): Promise<ActivityResponse> => {
    const { data } = await http.get<ActivityResponse>("/dm/personal/activity")
    return data
  },

  getAccess: async (): Promise<PersonalAccess> => {
    const { data } = await http.get<PersonalAccess>("/dm/personal/access")
    return data
  },

  withdraw: async (reviewId: number): Promise<WithdrawResult> => {
    const { data } = await http.post<WithdrawResult>(`/dm/reviews/${reviewId}/withdraw`)
    return data
  },
}
