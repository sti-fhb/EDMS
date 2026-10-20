import { useQuery } from "@tanstack/react-query"

import { dashboardApi } from "./dashboardService"

/** 各類型文件總數（4 內建分類 + 總計）。 */
export function useDashboardStats() {
  return useQuery({ queryKey: ["dm-dashboard", "stats"], queryFn: dashboardApi.getStats })
}

/** 最新更新公告（最新 10 筆已發布；筆數上限由後端 `_ANNOUNCE_LIMIT` 決定，#758 已移除時間窗）。 */
export function useAnnouncements() {
  return useQuery({ queryKey: ["dm-dashboard", "announcements"], queryFn: dashboardApi.getAnnouncements })
}
