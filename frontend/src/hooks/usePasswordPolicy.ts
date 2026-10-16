import { useQuery } from "@tanstack/react-query"

import { profileApi } from "../dp/user/profileService"
import type { PasswordRules } from "../dp/user/profileService"
import { toApiError } from "../services/http"

/**
 * 門檻要以誰的身分判定（#623）。
 *
 * - `public`：不知道是誰、或帳號尚無任何角色（註冊、啟用帳號）→ 一般門檻
 * - `self`：已登入者本人（變更密碼視窗、強制變更密碼頁）
 * - `reset`：信中重設連結的 token 對應帳號（重設密碼頁，未登入）
 */
export type PasswordPolicySource = { kind: "public" } | { kind: "self" } | { kind: "reset"; token: string }

/**
 * 門檻的狀態（#673）。呼叫端**必須分得出來**——說錯比不說更糟。
 *
 * ⚠️ 此處刻意不寫「共 N 種」：數字與下方清單是兩份會各自漂移的東西，新增一種狀態時
 * 最容易漏改的就是那個數字。以型別本身為準。
 *
 * - `loading`：還在取
 * - `ready`：取到了，`policy` 有值
 * - `token-invalid`：**僅 `reset`** —— 信中連結已失效（後端 `DP_PWD_005`），該頁應改顯示失效提示
 * - `unavailable`：取不到（限流 / 連線異常 / 伺服器錯誤）。⚠️ 連結**可能是好的**，
 *   不得據此說「連結已失效」
 */
export type PasswordPolicyStatus = "loading" | "ready" | "token-invalid" | "unavailable"

const PUBLIC: PasswordPolicySource = { kind: "public" }

/** 門檻未知時的提示——**不報出任何數字**，理由見 `buildPasswordHint`。 */
const HINT_LOADING = "密碼規則載入中…"
const HINT_UNAVAILABLE = "目前無法取得密碼規則，仍可送出，將以伺服器檢核為準"

/**
 * 讀密碼門檻並提供動態提示組字（US8 / 併 #77、#623、#673）。
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
 *
 * ## 取不到門檻時回 `unavailable`，**不是**悄悄退回 8（#673）
 *
 * 退回寫死的 8 會把 #623 修掉的矛盾在「取不到」時原樣復發——管理者看到 8、送出被 12 擋下。
 * 現在三種狀態分開，呼叫端自行決定要顯示什麼。
 */
export function usePasswordPolicy(source: PasswordPolicySource = PUBLIC): {
  policy: PasswordRules | undefined
  hint: string
  status: PasswordPolicyStatus
} {
  const enabled = source.kind !== "reset" || source.token !== ""
  const { data: policy, error } = useQuery({
    queryKey: ["password-policy", source],
    queryFn: () => fetchRules(source),
    // 重設頁沒有 token 時不發請求（頁面本身已顯示連結無效）
    enabled,
    // 每次開啟變更密碼 / 強制變更 / 重設頁即重取，確保提示數字反映最新參數（併 #77 即時性）。
    staleTime: 0,
    // 頁面存活期間門檻幾乎不變，切回視窗不必重取。⚠️ 重設頁的門檻端點有 IP 限流（10 次 / 分），
    // 切視窗去密碼管理員複製密碼若每次都重打，會吃滿額度回 429，門檻變成 `unavailable`。
    refetchOnWindowFocus: source.kind === "public",
    // 🔴 4xx 不重試（#673）。失效連結是**確定的答案**，重打只是拿同一個 400 回來，而這個端點
    // 與 `/reset-password` 共用同一個 IP 限流器（10 次 / 分）——預設 `retry: 3` 會讓一條死連結
    // 打掉 4 次額度，使用者多點兩次信就把真正要用的重設額度吃光。
    //
    // ⚠️ **本行的守門測試不在一般 harness 裡**：正式環境是 `main.tsx` 的 `new QueryClient()`
    // （預設 retry 3），而所有測試 harness 都設 `retry: false`（見 `test/renderWithProviders.tsx`
    // 與各 auth 測試）——沿用 harness 的測試**永遠觀察不到重試**（實測：刪掉本行，該檔 10 條全過）。
    // 守它的是 `ResetPasswordPage.test.tsx` 的「死連結不得重試」，那條**自己傳一個未關重試的
    // QueryClient**。⛔ 新增同類守門時要照做，否則又會寫出一行沒人驗得到的設定。
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const status = resolveStatus({ policy, error })
  return { policy, hint: buildHint(status, policy), status }
}

/**
 * ⚠️ 查詢被 `enabled: false` 停用時（重設頁無 token）落在 `loading`——該頁在檢查 `status`
 * 之前就先以 `token === ""` 顯示「連結無效」，故不另設狀態。
 */
function resolveStatus(args: { policy: PasswordRules | undefined; error: unknown }): PasswordPolicyStatus {
  if (args.policy !== undefined) return "ready"
  if (args.error === null || args.error === undefined) return "loading"
  // DP_PWD_005＝信中連結查無 / 已用 / 逾期（後端 `password_rules_for_token`）。
  // 其餘一律 `unavailable`——429 / 連線異常不代表連結壞了。
  return toApiError(args.error).errorCode === "DP_PWD_005" ? "token-invalid" : "unavailable"
}

function buildHint(status: PasswordPolicyStatus, policy: PasswordRules | undefined): string {
  if (status === "ready" && policy !== undefined) return buildPasswordHint(policy)
  if (status === "loading") return HINT_LOADING
  // `token-invalid` 的頁面不會渲染表單，提示給空字串即可
  return status === "unavailable" ? HINT_UNAVAILABLE : ""
}

function fetchRules(source: PasswordPolicySource): Promise<PasswordRules> {
  if (source.kind === "self") return profileApi.getMyPasswordRules()
  if (source.kind === "reset") return profileApi.getResetPasswordRules(source.token)
  return profileApi.getPasswordPolicy()
}

/**
 * 由密碼門檻組出提示字（純函式）。
 *
 * ⛔ **門檻未知時不要在這裡補預設值**（原為 `?? 8` / `?? 3`，#673 移除）：那會讓取不到門檻的
 * 畫面**自信地報出錯的數字**。未知該走 `PasswordPolicyStatus` 的 `unavailable`，由呼叫端
 * 顯示「不知道」而非一個數字。
 */
export function buildPasswordHint(policy: PasswordRules): string {
  return `至少 ${policy.min_len} 字元，含大小寫英文 / 數字 / 特殊符號至少 ${policy.char_types} 種`
}
