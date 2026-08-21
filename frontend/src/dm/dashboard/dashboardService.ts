import type { AnnouncementItem, DashboardStats } from "./schemas"
import { http } from "../../services/http"

/** 系統儀表板 API（US7 / DM00，唯讀）。 */
export const dashboardApi = {
  getStats: async (): Promise<DashboardStats> => {
    const { data } = await http.get<DashboardStats>("/dm/dashboard/stats")
    return data
  },

  getAnnouncements: async (): Promise<AnnouncementItem[]> => {
    const { data } = await http.get<AnnouncementItem[]>("/dm/dashboard/announcements")
    return data
  },
}
