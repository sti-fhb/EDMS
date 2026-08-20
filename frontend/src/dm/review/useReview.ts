import { useQuery } from "@tanstack/react-query"

import { reviewApi } from "./reviewService"

/** 待簽核清單（指派給自己之 PENDING）。 */
export function usePending() {
  return useQuery({ queryKey: ["dm-review", "pending"], queryFn: reviewApi.listPending })
}

/** 簽核明細（展開某列時才載入）。 */
export function useReviewDetail(reviewId: number | null) {
  return useQuery({
    queryKey: ["dm-review", "detail", reviewId],
    queryFn: () => reviewApi.getDetail(reviewId!),
    enabled: reviewId != null,
  })
}

/** 已完成清單（後端分頁）。 */
export function useCompleted(page: number, limit: number) {
  return useQuery({
    queryKey: ["dm-review", "completed", page, limit],
    queryFn: () => reviewApi.listCompleted(page, limit),
  })
}
