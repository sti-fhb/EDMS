import type { APIRequestContext } from "@playwright/test"

import { BASE_URL, MAILPIT_URL, MAIL_WAIT_TIMEOUT_MS } from "./env"

/**
 * 從 mailpit 取信中連結（#57）。
 *
 * 為什麼不從 DB 取：token 在 DB 只存雜湊，拿不到明文；且自 #859 起，已寄出（SENT）的
 * 重設信內文會在 outbox 被遮罩。信箱是唯一拿得到明文連結的地方——這也正是使用者走的路。
 */

type LinkPath = "/verify-email" | "/reset-password"

interface MailpitSummary {
  ID: string
}

interface MailpitSearchResult {
  messages: MailpitSummary[]
}

interface MailpitMessage {
  Text: string
}

const escapeRegExp = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

async function findLink(request: APIRequestContext, to: string, path: LinkPath): Promise<string | null> {
  const search = await request.get(`${MAILPIT_URL}/api/v1/search`, {
    params: { query: `to:"${to}"` },
  })
  if (!search.ok()) throw new Error(`mailpit 搜尋失敗：HTTP ${search.status()}`)
  const { messages } = (await search.json()) as MailpitSearchResult

  // mailpit 依時間新到舊排序；同一收件人可能有多封（如先驗證信、後重設信），逐封找指定路徑的連結
  const pattern = new RegExp(`${escapeRegExp(BASE_URL)}${escapeRegExp(path)}\\?token=[^\\s"'<>]+`)
  for (const { ID } of messages) {
    const res = await request.get(`${MAILPIT_URL}/api/v1/message/${ID}`)
    if (!res.ok()) throw new Error(`mailpit 讀信失敗：HTTP ${res.status()}`)
    const { Text } = (await res.json()) as MailpitMessage
    const match = pattern.exec(Text)
    if (match) return match[0]
  }
  return null
}

/**
 * 輪詢 mailpit，直到收件人收到含指定連結的信，回傳完整連結。
 *
 * 逾時訊息刻意點出最常見的成因：信卡在 outbox（worker 沒起來 / SMTP 連不到 mailpit），
 * 而不是頁面壞了——兩者在 trace 上看起來都只是「等不到」。
 */
export async function waitForMailLink(request: APIRequestContext, to: string, path: LinkPath): Promise<string> {
  const deadline = Date.now() + MAIL_WAIT_TIMEOUT_MS
  while (Date.now() < deadline) {
    const link = await findLink(request, to, path)
    if (link !== null) return link
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(
    `${MAIL_WAIT_TIMEOUT_MS / 1000} 秒內 mailpit 沒收到寄給 ${to} 的 ${path} 信。` +
      "請先確認：mailpit 是否在跑、後端 MAIL_SERVER/MAIL_PORT 是否指向它、" +
      "後端 log 有無「發信 worker 輪詢失敗」。",
  )
}

/** 啟動前確認 mailpit 可連，連不到就直接說清楚，而不是讓每條測試各自等滿 30 秒。 */
export async function assertMailpitReachable(request: APIRequestContext): Promise<void> {
  try {
    const res = await request.get(`${MAILPIT_URL}/api/v1/info`)
    if (res.ok()) return
    throw new Error(`HTTP ${res.status()}`)
  } catch (err) {
    throw new Error(`連不到 mailpit（${MAILPIT_URL}）：${String(err)}。本機啟動方式見 e2e/README.md。`)
  }
}
