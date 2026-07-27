import { http } from "../../services/http"

/** 個人資料（US8）：本人姓名 / 帳號（Email）/ 待驗證新信箱。 */
export interface MeResponse {
  user_id: string
  email: string
  user_name: string
  /** 有值代表已申請 Email 變更、尚未驗證（顯示「變更審核中」）；null 代表無待驗證變更。 */
  pending_email: string | null
}

export interface PasswordChangeRequest {
  old_password: string
  new_password: string
  confirm_password: string
}

/** 公開密碼政策（US8 / 併 #77）：供動態渲染提示；僅非機密門檻數值。 */
export interface PasswordPolicy {
  min_len: number
  admin_min_len: number
  char_types: number
  history_count: number
  expiry_days: number
}

/** 個人資料 API（US8）。路徑相對於 baseURL（/api）。 */
export const profileApi = {
  async getMe(): Promise<MeResponse> {
    const { data } = await http.get<MeResponse>("/dp/user/me")
    return data
  },
  async updateName(userName: string): Promise<void> {
    await http.put("/dp/user/me", { user_name: userName })
  },
  async changePassword(payload: PasswordChangeRequest): Promise<void> {
    await http.put("/dp/user/me/password", payload)
  },
  async requestEmailChange(newEmail: string): Promise<void> {
    await http.put("/dp/user/me/email", { new_email: newEmail })
  },
  async verifyEmailChange(token: string): Promise<void> {
    await http.post("/verify-email-change", { token })
  },
  async getPasswordPolicy(): Promise<PasswordPolicy> {
    const { data } = await http.get<PasswordPolicy>("/password-policy")
    return data
  },
}
