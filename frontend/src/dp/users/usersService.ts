import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"

/** 使用者清單列（對齊後端 UserResponse）。status 為原始 ACTIVE/DISABLED；鎖定由 locked_until 衍生。 */
export interface UserRow {
  user_id: string
  user_name: string
  email: string
  status: string
  locked_until: string | null
  last_login_date: string | null
  created_date: string | null
}

export interface UserCreatePayload {
  email: string
  user_name: string
  password: string
}

export interface UserUpdatePayload {
  user_name: string
  email: string
}

export interface ListUsersParams {
  q?: string
  status?: string
  page: number
  limit: number
}

/** 使用者管理 API（US4）。路徑相對於 baseURL（/api）。 */
export const usersApi = {
  async list(params: ListUsersParams): Promise<PagedResult<UserRow>> {
    const { data } = await http.get<PagedResult<UserRow>>("/dp/users", { params })
    return data
  },
  async create(payload: UserCreatePayload): Promise<UserRow> {
    const { data } = await http.post<UserRow>("/dp/users", payload)
    return data
  },
  async updateBasic(userId: string, payload: UserUpdatePayload): Promise<UserRow> {
    const { data } = await http.patch<UserRow>(`/dp/users/${userId}`, payload)
    return data
  },
  async setStatus(userId: string, action: "disable" | "enable"): Promise<UserRow> {
    const { data } = await http.patch<UserRow>(`/dp/users/${userId}/status`, { action })
    return data
  },
  async unlock(userId: string): Promise<UserRow> {
    const { data } = await http.patch<UserRow>(`/dp/users/${userId}/unlock`)
    return data
  },
}
