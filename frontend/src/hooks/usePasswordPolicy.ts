import { useQuery } from "@tanstack/react-query"

import { profileApi } from "../dp/user/profileService"
import type { PasswordPolicy } from "../dp/user/profileService"

/**
 * 讀公開密碼政策並提供動態提示組字（US8 / 併 #77 核心）。
 *
 * 提示**數字**（最小長度、字元組合種類數）動態讀 `PWD_POLICY` 參數即時反映——
 * 管理者於 US5 改參數，提示跟著變、非寫死。政策為公開端點（免 JWT），供變更密碼 /
 * 註冊 / 重設頁共用。
 *
 * ⚠️ 一般 8 / 特權 12 之**選擇**由後端依 is_module_admin 判定（前端不判斷身分）；
 * 過渡期（T017 stub）一律顯示一般門檻，特權提示待模組 service 就緒（T049）。
 */
export function usePasswordPolicy(): { policy: PasswordPolicy | undefined; hint: string } {
  const { data: policy } = useQuery({
    queryKey: ["password-policy"],
    queryFn: profileApi.getPasswordPolicy,
    staleTime: 5 * 60 * 1000, // 政策不常變；5 分鐘內共用快取即可
  })
  const hint = buildPasswordHint(policy)
  return { policy, hint }
}

/** 由密碼政策組出提示字（純函式，供 hook 與測試共用）。政策未載入時回保守預設。 */
export function buildPasswordHint(policy: PasswordPolicy | undefined): string {
  const minLen = policy?.min_len ?? 8
  const charTypes = policy?.char_types ?? 3
  return `至少 ${minLen} 字元，含大小寫英文 / 數字 / 特殊符號至少 ${charTypes} 種`
}
