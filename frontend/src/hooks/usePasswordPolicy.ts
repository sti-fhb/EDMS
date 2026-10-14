import { useQuery } from "@tanstack/react-query"

import { profileApi } from "../dp/user/profileService"
import type { PasswordRules } from "../dp/user/profileService"

/**
 * 門檻要以誰的身分判定（#623）。
 *
 * - `public`：不知道是誰、或帳號尚無任何角色（註冊、啟用帳號）→ 一般門檻
 * - `self`：已登入者本人（變更密碼視窗、強制變更密碼頁）
 * - `reset`：信中重設連結的 token 對應帳號（重設密碼頁，未登入）
 */
export type PasswordPolicySource = { kind: "public" } | { kind: "self" } | { kind: "reset"; token: string }

const PUBLIC: PasswordPolicySource = { kind: "public" }

/**
 * 讀密碼門檻並提供動態提示組字（US8 / 併 #77、#623）。
 *
 * 提示**數字**（最小長度、字元組合種類數）動態讀 `PWD_POLICY` 參數，管理者於 DP03 改參數即反映。
 *
 * ## 🔴 特權 12 / 一般 8 由後端依身分判定，前端只負責問對端點（#623）
 *
 * 原本一律讀公開政策的 `min_len`（一般門檻），管理者照提示設 8～11 字元，前端放行、送出才被
 * 後端以 12 字元擋下，提示與錯誤訊息互相矛盾。⛔ 不要在前端自行判斷「是不是管理者」再挑
 * `admin_min_len`：強制變更密碼頁處於密碼閘之後，查角色的端點會被擋，而判定邏輯應只有後端
 * `password_rules` 一份。
 *
 * 回傳的 `policy` 即送出時後端檢核所用的同一組門檻，提示與前端檢核都以它為準。
 */
export function usePasswordPolicy(source: PasswordPolicySource = PUBLIC): {
  policy: PasswordRules | undefined
  hint: string
} {
  const { data: policy } = useQuery({
    queryKey: ["password-policy", source],
    queryFn: () => fetchRules(source),
    // 重設頁沒有 token 時不發請求（頁面本身已顯示連結無效）
    enabled: source.kind !== "reset" || source.token !== "",
    // 每次開啟變更密碼 / 強制變更 / 重設頁即重取，確保提示數字反映最新參數（併 #77 即時性）。
    staleTime: 0,
    // 頁面存活期間門檻幾乎不變，切回視窗不必重取。⚠️ 重設頁的門檻端點有 IP 限流（10 次 / 分），
    // 切視窗去密碼管理員複製密碼若每次都重打，會吃滿額度回 429，`policy` 退回 undefined 而提示
    // 掉回一般 8 字元——正是 #623 要修的矛盾，只是換成在限流時復發。
    refetchOnWindowFocus: source.kind === "public",
  })
  const hint = buildPasswordHint(policy)
  return { policy, hint }
}

function fetchRules(source: PasswordPolicySource): Promise<PasswordRules> {
  if (source.kind === "self") return profileApi.getMyPasswordRules()
  if (source.kind === "reset") return profileApi.getResetPasswordRules(source.token)
  return profileApi.getPasswordPolicy()
}

/** 由密碼門檻組出提示字（純函式，供 hook 與測試共用）。門檻未載入時回保守預設。 */
export function buildPasswordHint(policy: PasswordRules | undefined): string {
  const minLen = policy?.min_len ?? 8
  const charTypes = policy?.char_types ?? 3
  return `至少 ${minLen} 字元，含大小寫英文 / 數字 / 特殊符號至少 ${charTypes} 種`
}
