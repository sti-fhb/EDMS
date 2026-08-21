import { useQuery } from "@tanstack/react-query"

import { dashboardApi } from "./dashboardService"

/** 各類型文件總數（4 內建分類 + 總計）。 */
export function useDashboardStats() {
  return useQuery({ queryKey: ["dm-dashboard", "stats"], queryFn: dashboardApi.getStats })
}

/** 最新更新公告（近 30 天已發布）。 */
export function useAnnouncements() {
  return useQuery({ queryKey: ["dm-dashboard", "announcements"], queryFn: dashboardApi.getAnnouncements })
}
