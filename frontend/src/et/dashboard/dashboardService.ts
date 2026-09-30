import type { EtDashboard } from "./dashboardSchemas"
import { http } from "../../services/http"

export const etDashboardApi = {
  get: async (): Promise<EtDashboard> => {
    const { data } = await http.get<EtDashboard>("/et/dashboard")
    return data
  },
}
