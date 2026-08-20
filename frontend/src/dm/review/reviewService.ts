import type { ApproveResult, CompletedItem, PendingItem, RejectResult, ReviewDetail } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"
import { http } from "../../services/http"

/** 簽核中心 API（US6 / DM04）。 */
export const reviewApi = {
  listPending: async (): Promise<PendingItem[]> => {
    const { data } = await http.get<PendingItem[]>("/dm/reviews/pending")
    return data
  },

  getDetail: async (reviewId: number): Promise<ReviewDetail> => {
    const { data } = await http.get<ReviewDetail>(`/dm/reviews/${reviewId}`)
    return data
  },

  approve: async (reviewId: number): Promise<ApproveResult> => {
    const { data } = await http.post<ApproveResult>(`/dm/reviews/${reviewId}/approve`)
    return data
  },

  reject: async (reviewId: number, reason: string): Promise<RejectResult> => {
    const { data } = await http.post<RejectResult>(`/dm/reviews/${reviewId}/reject`, { reason })
    return data
  },

  listCompleted: async (page: number, limit: number, keyword = ""): Promise<PagedResult<CompletedItem>> => {
    const { data } = await http.get<PagedResult<CompletedItem>>("/dm/reviews/completed", {
      params: { page, limit, keyword: keyword || undefined },
    })
    return data
  },
}
