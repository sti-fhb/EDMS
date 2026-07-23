import { http } from "../../services/http"

/** 參數明細（對齊後端 ParamDetailResponse）。 */
export interface ParamDetail {
  param_key: string
  param_value: string | null
  sort_order: number | null
  is_enabled: boolean
}

/** 參數主檔 + 明細（對齊後端 ParamMasterResponse）。scope 依 PARAM_ID 前綴衍生。 */
export interface ParamMaster {
  param_id: string
  param_name: string
  param_type: "VALUE" | "LIST"
  detail_lock: boolean
  description: string | null
  scope: "platform" | "ET" | "DM"
  details: ParamDetail[]
}

export interface DetailUpdatePayload {
  param_value?: string
  is_enabled?: boolean
}

export interface DetailCreatePayload {
  param_key: string
  param_value: string
  sort_order?: number
}

/** 系統參數維護 API（US5）。路徑相對於 baseURL（/api）。 */
export const paramsApi = {
  async list(): Promise<ParamMaster[]> {
    const { data } = await http.get<ParamMaster[]>("/dp/params")
    return data
  },
  async updateDetail(paramId: string, paramKey: string, payload: DetailUpdatePayload): Promise<ParamDetail> {
    const { data } = await http.put<ParamDetail>(`/dp/params/${paramId}/details/${paramKey}`, payload)
    return data
  },
  async createDetail(paramId: string, payload: DetailCreatePayload): Promise<ParamDetail> {
    const { data } = await http.post<ParamDetail>(`/dp/params/${paramId}/details`, payload)
    return data
  },
}
