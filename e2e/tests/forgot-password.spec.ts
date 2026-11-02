import { expect, test } from "@playwright/test"

import { createVerifiedAccount, loginViaUi, newAccount } from "../support/accounts"
import { waitForMailLink } from "../support/mailpit"

/**
 * Critical path 3：忘記密碼 → 重設 → 以新密碼登入（#57）。
 */
test("忘記密碼後經信中連結重設，可用新密碼登入", async ({ page, request }) => {
  const account = newAccount("forgot")
  await createVerifiedAccount(request, account)
  const newPassword = `${account.password}-New2`

  await page.goto("/")
  await page.getByRole("button", { name: "忘記密碼？" }).click()
  await page.getByLabel("帳號（Email）").fill(account.email)
  await page.getByRole("button", { name: "送出" }).click()
  await expect(page.getByText("若該 Email 已註冊，密碼重設信將寄至信箱")).toBeVisible()

  const link = await waitForMailLink(request, account.email, "/reset-password")
  await page.goto(link)
  await expect(page.getByRole("heading", { name: "重設密碼" })).toBeVisible()
  await page.getByLabel("新密碼", { exact: true }).fill(newPassword)
  await page.getByLabel("確認新密碼").fill(newPassword)
  await page.getByRole("button", { name: "重設密碼" }).click()
  await expect(page.getByText("密碼已更新，請以新密碼登入")).toBeVisible()

  await page.getByRole("link", { name: "返回登入" }).click()
  await loginViaUi(page, account.email, newPassword, account.name)
})
