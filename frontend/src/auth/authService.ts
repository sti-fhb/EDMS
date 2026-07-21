import { http } from "../services/http"

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  must_change_pwd: boolean
}

export interface TokenResponse {
  access_token: string
}

export interface RegisterRequest {
  email: string
  user_name: string
  password: string
  confirm_password: string
}

export interface ResetPasswordRequest {
  token: string
  new_password: string
  confirm_password: string
}

export interface ModuleRoleStatus {
  has_role: boolean
}

export interface ModuleSummary {
  et: ModuleRoleStatus
  dm: ModuleRoleStatus
}

/** 認證 API（US1）：登入 / 換發 / 登出 / 入口頁模組摘要。路徑相對於 baseURL（/api）。 */
export const authApi = {
  async register(payload: RegisterRequest): Promise<void> {
    await http.post("/register", payload)
  },
  async forgotPassword(email: string): Promise<void> {
    await http.post("/forgot-password", { email })
  },
  async resetPassword(payload: ResetPasswordRequest): Promise<void> {
    await http.post("/reset-password", payload)
  },
  async login(payload: LoginRequest): Promise<LoginResponse> {
    const { data } = await http.post<LoginResponse>("/login", payload)
    return data
  },
  async renew(): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>("/dp/user/renew")
    return data
  },
  async logout(): Promise<void> {
    await http.post("/dp/user/logout")
  },
  async moduleSummary(): Promise<ModuleSummary> {
    const { data } = await http.get<ModuleSummary>("/dp/user/module-summary")
    return data
  },
}
