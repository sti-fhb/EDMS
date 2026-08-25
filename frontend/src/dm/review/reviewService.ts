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

  fetchFileBlob: async (reviewId: number, versionId: number): Promise<Blob> => {
    const { data } = await http.get<Blob>(`/dm/reviews/${reviewId}/versions/${versionId}/file`, {
      responseType: "blob",
    })
    return data
  },

  fetchObsoleteFileBlob: async (reviewId: number): Promise<Blob> => {
    const { data } = await http.get<Blob>(`/dm/reviews/${reviewId}/obsolete-file`, { responseType: "blob" })
    return data
  },
}

/** 下載廢止附件（US8，授權 Q1=C：DM_ADMIN 或指定審核者）。 */
export async function downloadObsoleteFile(reviewId: number, filename: string): Promise<void> {
  const blob = await reviewApi.fetchObsoleteFileBlob(reviewId)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 下載簽核明細之待審版 / 目前發布版檔案（走 US6 審核端點，可取未發布之待審版）。 */
export async function downloadReviewFile(reviewId: number, versionId: number, filename: string): Promise<void> {
  const blob = await reviewApi.fetchFileBlob(reviewId, versionId)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
