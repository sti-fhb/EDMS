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

/** 某帳號設定新密碼時**實際適用**之門檻（#623）：管理者 min_len 為 12、其餘為 8，由後端判定。 */
export interface PasswordRules {
  min_len: number
  char_types: number
}

/** getMe 的共用 query key；WelcomePage / ProfilePage 共用同一快取（單一事實來源，避免字面值漂移）。 */
export const PROFILE_ME_QUERY_KEY = ["profile", "me"] as const

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
  // 回傳後端 retry_after（寄信冷卻秒數，#74），供前端起算倒數；無則 undefined。
  async requestEmailChange(newEmail: string): Promise<number | undefined> {
    const { data } = await http.put<{ retry_after?: number }>("/dp/user/me/email", { new_email: newEmail })
    return data.retry_after
  },
  async verifyEmailChange(token: string): Promise<void> {
    await http.post("/verify-email-change", { token })
  },
  async getPasswordPolicy(): Promise<PasswordPolicy> {
    const { data } = await http.get<PasswordPolicy>("/password-policy")
    return data
  },
  /** 登入者本人適用之門檻（#623）；密碼逾期、尚在強制變更頁時亦可取得。 */
  async getMyPasswordRules(): Promise<PasswordRules> {
    const { data } = await http.get<PasswordRules>("/dp/user/me/password-policy")
    return data
  },
  /** 重設連結 token 對應帳號適用之門檻（#623）。token 放 body：放網址會被代理伺服器記進存取紀錄。 */
  async getResetPasswordRules(token: string): Promise<PasswordRules> {
    const { data } = await http.post<PasswordRules>("/reset-password/policy", { token })
    return data
  },
}
