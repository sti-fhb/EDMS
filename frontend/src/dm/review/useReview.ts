import { useQuery } from "@tanstack/react-query"

import { reviewApi } from "./reviewService"

/** 待簽核清單（指派給自己之 PENDING、後端分頁；#503 起比照已完成頁籤）。 */
export function usePending(page: number, limit: number) {
  return useQuery({
    queryKey: ["dm-review", "pending", page, limit],
    queryFn: () => reviewApi.listPending(page, limit),
  })
}

/** 簽核明細（展開某列時才載入）。 */
export function useReviewDetail(reviewId: number | null) {
  return useQuery({
    queryKey: ["dm-review", "detail", reviewId],
    queryFn: () => reviewApi.getDetail(reviewId!),
    enabled: reviewId != null,
  })
}

/** 已完成清單（後端分頁 + 文件名關鍵字搜尋）。 */
export function useCompleted(page: number, limit: number, keyword = "") {
  return useQuery({
    queryKey: ["dm-review", "completed", page, limit, keyword],
    queryFn: () => reviewApi.listCompleted(page, limit, keyword),
  })
}
