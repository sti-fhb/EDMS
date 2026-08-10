import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"

/** 權限管理列（對齊後端 AssignmentItem）。roles / groups 為代碼集合（兩維度獨立）。 */
export interface AssignmentRow {
  user_id: string
  user_name: string
  email: string
  roles: string[]
  groups: string[]
  last_modified_by: string | null
  last_modified_by_name: string | null
  last_modified_date: string | null
}

/** 群組可選項（DM 可見對象 / ET 受訓單位標籤）。 */
export interface GroupOption {
  code: string
  name: string
}

export interface ListAssignmentsParams {
  module: string
  keyword?: string
  page: number
  limit: number
}

/** 權限管理轉接層 API（DP 為轉接、實際寫入在各模組 provider）。 */
export const rolesApi = {
  /** 當前使用者可管理之模組（決定顯示哪些頁籤）。 */
  modules: async (): Promise<string[]> => {
    const { data } = await http.get<string[]>("/dp/roles/modules")
    return data
  },

  /** 列一頁使用者 + 該模組角色 / 群組現況。 */
  list: async ({ module, keyword, page, limit }: ListAssignmentsParams): Promise<PagedResult<AssignmentRow>> => {
    const { data } = await http.get<PagedResult<AssignmentRow>>(`/dp/roles/${module}/assignments`, {
      params: { keyword: keyword || undefined, page, limit },
    })
    return data
  },

  /** 群組可選清單（僅列啟用中）。 */
  groupOptions: async (module: string): Promise<GroupOption[]> => {
    const { data } = await http.get<GroupOption[]>(`/dp/roles/${module}/group-options`)
    return data
  },

  /** 設定某使用者於該模組之角色 + 群組（完整目標集，兩維度獨立）。 */
  assign: async (module: string, userId: string, payload: { roles: string[]; groups: string[] }): Promise<void> => {
    await http.put(`/dp/roles/${module}/assignments/${userId}`, payload)
  },
}

/**
 * 各模組固定角色 enum（畫面無新增角色入口；對齊 spec_us7 / DM authz / ET 規格）。
 * ⚠️ 與後端權威定義（`backend/app/dm/roles/authz.py` `DM_ROLES` 等）**手動同步**——
 * 後端角色 enum 調整時須一併更新此處，否則前端會少顯示欄位或送出後端 422（DM_ROLE_003）。
 * TODO(#140-followup): 評估由 `/dp/roles/modules` 或新端點一併回傳角色 metadata，消除雙寫。
 */
export const MODULE_ROLES: Record<string, { code: string; label: string }[]> = {
  DM: [
    { code: "DM_ADMIN", label: "管理者" },
    { code: "DM_EDITOR", label: "編輯者" },
    { code: "DM_REVIEWER", label: "審核者" },
    { code: "DM_VIEWER", label: "閱覽者" },
  ],
  ET: [
    { code: "ET_ADMIN", label: "管理者" },
    { code: "ET_TEACHER", label: "教師" },
    { code: "ET_STUDENT", label: "學員" },
  ],
}

/** 模組代碼 → 頁籤顯示名。 */
export const MODULE_LABELS: Record<string, string> = { DM: "文件管理（DM）", ET: "教育訓練（ET）" }