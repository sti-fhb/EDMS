import { randomBytes } from "node:crypto"

import { expect } from "@playwright/test"
import type { APIRequestContext, Page } from "@playwright/test"

import { waitForMailLink } from "./mailpit"

/**
 * 測試帳號：每條測試自建、帶隨機尾碼，不依賴示範帳號 seed（E2E 設 SEED_DEMO_ACCOUNTS=false）。
 *
 * Email 用 example.com（RFC 2606 保留網域，不會寄到真人）；信實際上只會進 mailpit。
 */
export interface TestAccount {
  email: string
  name: string
  password: string
}

export function newAccount(label: string): TestAccount {
  const suffix = `${Date.now().toString(36)}${randomBytes(3).toString("hex")}`
  return {
    email: `e2e-${label}-${suffix}@example.com`,
    name: `E2E ${label} ${suffix}`,
    // 長度與四種字元類型皆遠超預設密碼政策（最小 8、至少 3 類）
    password: `E2e-${suffix}-Pw1!`,
  }
}

/** 由前端同源的 /api 呼叫（經 vite preview 代理），與瀏覽器走同一條路。 */
function apiPath(path: string): string {
  return `/api${path}`
}

/**
 * 以 API 建立一個「已驗證、可登入」的帳號：註冊 → 從 mailpit 取驗證連結 → 設定密碼。
 *
 * 這是**前置條件**，不是被測對象（註冊流程本身由 register.spec.ts 走 UI 驗證），
 * 故走 API 以縮短時間、減少與本條測試無關的失敗點。
 */
export async function createVerifiedAccount(request: APIRequestContext, account: TestAccount): Promise<void> {
  const register = await request.post(apiPath("/register"), {
    data: { email: account.email, user_name: account.name },
  })
  expect(register.status(), "註冊 API 應回 202").toBe(202)

  const link = await waitForMailLink(request, account.email, "/verify-email")
  const token = new URL(link).searchParams.get("token")
  expect(token, "驗證連結應帶 token").toBeTruthy()

  const verify = await request.post(apiPath("/verify-email"), {
    data: { token, new_password: account.password, confirm_password: account.password },
  })
  expect(verify.ok(), `設定密碼 API 應成功（HTTP ${verify.status()}）`).toBe(true)
}

/** 從登入 overlay 以帳密登入，並確認已進入登入後的歡迎頁。 */
export async function loginViaUi(page: Page, email: string, password: string, name: string): Promise<void> {
  await page.goto("/")
  await page.getByLabel("帳號（Email）").fill(email)
  await page.getByLabel("密碼", { exact: true }).fill(password)
  await page.getByRole("button", { name: "登入", exact: true }).click()
  await expect(page.getByRole("heading", { name: `歡迎，${name}` })).toBeVisible()
}
