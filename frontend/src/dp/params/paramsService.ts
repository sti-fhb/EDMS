import { http } from "../../services/http"

/** 參數明細（對齊後端 ParamDetailResponse）。param_name＝中文顯示名稱；param_value＝實際值（可空）。 */
export interface ParamDetail {
  param_key: string
  param_name: string
  param_value: string | null
  description: string | null
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
  param_name?: string
  param_value?: string
  /** null＝清空說明（後端寫回 NULL）；省略＝不異動。 */
  description?: string | null
  is_enabled?: boolean
}

export interface DetailCreatePayload {
  param_key: string
  param_name: string
  param_value?: string
  description?: string
  sort_order?: number
}

/** 受控清單之單一項（模組自持表，非 DP_PARAM）。鎖定語意在**項目層**（is_builtin），與 DP_PARAM 的 detail_lock 不同。 */
export interface ControlledItem {
  code: string
  name: string
  is_builtin: boolean
  is_enabled: boolean
}

/** 受控清單之一個維護分區。有子分組者（DM 標籤依標籤組）每組一區，group_* 非空。 */
export interface ControlledSection {
  module: string
  kind: string
  name: string
  /** true＝新增時需使用者輸入代碼（DM 分類 / 作業項目）；false＝模組自行配號或由分區帶入。 */
  requires_code: boolean
  group_code: string | null
  group_name: string | null
  items: ControlledItem[]
}

/** 啟停結果；僅 DM 可見對象停用（soft-retire）帶受影響數。該數字為**下限**（見 #388）。 */
export interface ControlledToggleResult {
  affected_docs: number | null
  affected_viewers: number | null
}

/** 模組受控清單維護 API（#182）。 */
export const controlledApi = {
  async list(): Promise<ControlledSection[]> {
    const { data } = await http.get<ControlledSection[]>("/dp/params/controlled")
    return data
  },
  async create(module: string, kind: string, payload: { code?: string; name: string }): Promise<void> {
    await http.post(`/dp/params/controlled/${module}/${kind}`, payload)
  },
  async rename(module: string, kind: string, code: string, name: string): Promise<void> {
    await http.put(`/dp/params/controlled/${module}/${kind}/${encodeURIComponent(code)}`, { name })
  },
  async setEnabled(module: string, kind: string, code: string, enabled: boolean): Promise<ControlledToggleResult> {
    const { data } = await http.patch<ControlledToggleResult>(
      `/dp/params/controlled/${module}/${kind}/${encodeURIComponent(code)}/enabled`,
      { enabled },
    )
    return data
  },
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