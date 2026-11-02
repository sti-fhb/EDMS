import { expect, test } from "@playwright/test"

import { loginViaUi, newAccount } from "../support/accounts"
import { waitForMailLink } from "../support/mailpit"

/**
 * Critical path 2：自助註冊 → 信箱驗證（設定密碼）→ 登入（#57）。
 *
 * 註冊只收 Email 與姓名，密碼在點驗證連結後才設定（#212），故「驗證」與「設密碼」是同一步。
 */
test("自助註冊後經信箱驗證設定密碼，即可登入", async ({ page, request }) => {
  const account = newAccount("register")

  await page.goto("/")
  await page.getByRole("tab", { name: "註冊" }).click()
  await page.getByLabel("帳號（Email）").fill(account.email)
  await page.getByLabel("姓名").fill(account.name)
  await page.getByRole("button", { name: "建立帳號" }).click()
  await expect(page.getByText(`驗證信已寄至 ${account.email}`)).toBeVisible()

  const link = await waitForMailLink(request, account.email, "/verify-email")
  await page.goto(link)
  await expect(page.getByRole("heading", { name: "設定密碼以完成註冊" })).toBeVisible()
  await page.getByLabel("設定密碼").fill(account.password)
  await page.getByLabel("確認密碼").fill(account.password)
  await page.getByRole("button", { name: "設定密碼並啟用" }).click()
  await expect(page.getByText("帳號已啟用，請以新密碼登入")).toBeVisible()

  await page.getByRole("link", { name: "前往登入" }).click()
  await loginViaUi(page, account.email, account.password, account.name)
})
