import type { ActivityResponse, DraftItem, PersonalAccess, WithdrawResult } from "./schemas"
import { http } from "../../services/http"

/**
 * 個人專區 API（US9 / DM04）。
 *
 * ⚠️ 本檔路徑參數**刻意未編碼**，不是漏做（#624）：`reviewId` / `versionId` 皆為 `number`，
 * TypeScript 保證內插後不可能含 `/`，`encodeURIComponent` 是 no-op。對齊 ET 既有寫法
 * （`et/students/studentsService.ts` 只編碼字串的 `userId`、不編碼數字的 `courseId`）。
 * 日後若有參數改為 `string`，請一併加上編碼。
 */
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
