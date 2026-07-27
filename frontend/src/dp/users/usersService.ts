import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"

/** 正式帳號清單列（對齊後端 UserResponse）。status 為原始 ACTIVE/DISABLED；鎖定由 locked_until 衍生。 */
export interface UserRow {
  user_id: string
  user_name: string
  email: string
  status: string
  locked_until: string | null
  last_login_date: string | null
  created_date: string | null
}

/** 待啟用邀請列（對齊後端 InviteResponse，ADMIN_INVITE）。邀請狀態由 expires_date 衍生。 */
export interface InviteRow {
  res_id: string
  email: string
  user_name: string
  created_date: string | null
  expires_date: string
}

/** 建立帳號＝寄邀請（#67）：管理者不設密碼。 */
export interface UserCreatePayload {
  email: string
  user_name: string
}

/** 編輯：僅改姓名（Email 唯讀不可代改）。 */
export interface UserUpdatePayload {
  user_name: string
}

export interface ListUsersParams {
  q?: string
  status?: string
  page: number
  limit: number
}

export interface ListInvitesParams {
  q?: string
  page: number
  limit: number
}

/** 使用者管理 API（US4）。路徑相對於 baseURL（/api）。 */
export const usersApi = {
  async list(params: ListUsersParams): Promise<PagedResult<UserRow>> {
    const { data } = await http.get<PagedResult<UserRow>>("/dp/users", { params })
    return data
  },
  /** 建立帳號＝寄邀請信（後端 202 + message，不回傳 UserRow）。 */
  async create(payload: UserCreatePayload): Promise<void> {
    await http.post("/dp/users", payload)
  },
  async updateName(userId: string, payload: UserUpdatePayload): Promise<UserRow> {
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
  // --- 待啟用邀請（#67）---
  async listInvites(params: ListInvitesParams): Promise<PagedResult<InviteRow>> {
    const { data } = await http.get<PagedResult<InviteRow>>("/dp/users/invites", { params })
    return data
  },
  async resendInvite(resId: string): Promise<void> {
    await http.post(`/dp/users/invites/${resId}/resend`)
  },
  async cancelInvite(resId: string): Promise<void> {
    await http.delete(`/dp/users/invites/${resId}`)
  },
}