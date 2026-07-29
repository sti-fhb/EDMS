import { http } from "../../services/http"

export type Channel = "EMAIL" | "MSG" | "BOTH"

/** 通知範本（對齊後端 TemplateResponse）。 */
export interface Template {
  module: string
  template_code: string
  template_name: string
  subject: string
  body: string
  variables: string | null
  channel: Channel
  is_enabled: boolean
  is_system: boolean
  version: number
}

/** 更新範本 payload（含樂觀鎖 version）。 */
export interface TemplateUpdatePayload {
  subject: string
  body: string
  channel: Channel
  is_enabled: boolean
  version: number
}

/** 通知範本維護 API（US9）。路徑相對於 baseURL（/api）。 */
export const templatesApi = {
  async list(): Promise<Template[]> {
    const { data } = await http.get<Template[]>("/dp/notify/templates")
    return data
  },
  async update(module: string, code: string, payload: TemplateUpdatePayload): Promise<Template> {
    const { data } = await http.put<Template>(`/dp/notify/templates/${module}/${code}`, payload)
    return data
  },
}