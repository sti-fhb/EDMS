import { request } from "@playwright/test"

import { assertMailpitReachable } from "./mailpit"

/** 開跑前確認 mailpit 可連：連不到時一次說清楚，而不是每條測試各自等信等到逾時。 */
export default async function globalSetup(): Promise<void> {
  const ctx = await request.newContext()
  try {
    await assertMailpitReachable(ctx)
  } finally {
    await ctx.dispose()
  }
}
