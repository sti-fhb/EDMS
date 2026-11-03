import { expect, test } from "@playwright/test"

import { createVerifiedAccount, loginViaUi, newAccount } from "../support/accounts"

/**
 * Critical path 1：登入 → 模組入口頁（#57）。
 *
 * 自助註冊的帳號預設具 ET 學員角色，故以「教育訓練 › 我的課程」為模組入口；
 * 這條同時驗到 JWT 在頁面切換間有被帶上（入口頁的資料查詢需要認證）。
 */
test("登入後可由側欄進入模組入口頁（教育訓練 › 我的課程）", async ({ page, request }) => {
  const account = newAccount("login")
  await createVerifiedAccount(request, account)

  await loginViaUi(page, account.email, account.password, account.name)

  await page.getByRole("link", { name: "我的課程" }).click()

  await expect(page).toHaveURL(/\/et\/my-courses$/)
  await expect(page.getByRole("heading", { level: 1, name: "我的課程" })).toBeVisible()
  // 需認證的資料查詢有回來（不是只畫出空殼）：統計卡片出現
  await expect(page.getByText("已加入課程")).toBeVisible()
})
