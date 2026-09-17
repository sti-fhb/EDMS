/** cron 運算式 → 人類可讀執行時點（排程總覽用）。
 *
 * 存在的理由：執行時點的唯一事實來源是 `DP_SCHEDULE.CRON_EXPR`。說明欄曾經也寫著時點，
 * 但兩者沒有任何機制保持同步，實際歪過一次（#332）——所以時點改為一律由 cron 現算。
 */

/** day-of-week 值 → 中文。
 *
 * ⚠️ **索引 0 是週一，不是週日。** 後端以 APScheduler 的 `CronTrigger.from_crontab`
 * 驅動排程，而它把 day-of-week 直接塞進自己的欄位（`0=Monday`），**不做**標準 crontab
 * （`0=Sunday`）的轉換；旁證是 `7` 會被它直接拒絕（max 6），而標準 crontab 接受 7 為週日。
 *
 * 照標準 crontab 渲染的話，畫面會與實際觸發日整整差一天。
 */
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"] as const

/** 純十進位整數且落在範圍內才回值，否則 null（擋掉 `*`、範圍 `1-5`、間隔 `*∕2` 等非單值寫法）。 */
function parseField(raw: string, min: number, max: number): number | null {
  if (!/^\d{1,2}$/.test(raw)) return null
  const n = Number(raw)
  return n >= min && n <= max ? n : null
}

const pad = (n: number) => String(n).padStart(2, "0")

/** 回傳如「每日 08:00 UTC」「每週一 10:00 UTC」「每月 1 日 09:00 UTC」；無法判讀回 `null`。
 *
 * ⚠️ **時刻一律標 UTC，不換算本地時間。** 引擎以 `CronTrigger.from_crontab(..., timezone="UTC")`
 * 註冊，管理者在同一頁編輯的 `CRON_EXPR` 也是 UTC 運算式——顯示 UTC 才與他手上的欄位對得起來。
 * 若在此偷偷換成本地時間，畫面會出現「編輯框寫 10，旁邊顯示 18:00」的矛盾。本地時刻由
 * 同列的「下次執行」欄承擔（`formatDateTime` 走本地時區）。
 *
 * 只處理單值的每日 / 每週 / 每月三種常見形狀——涵蓋目前全部種子 job。其餘（間隔、
 * 範圍、清單、指定月份、dom 與 dow 同時指定）一律回 `null`，由呼叫端退回顯示原始運算式，
 * **不做近似猜測**：猜錯的時點比看不懂的 cron 更危險。
 */
export function formatCronSchedule(expr: string | null | undefined): string | null {
  if (!expr) return null
  const fields = expr.trim().split(/\s+/)
  if (fields.length !== 5) return null

  const [rawMin, rawHour, dom, month, dow] = fields
  const minute = parseField(rawMin, 0, 59)
  const hour = parseField(rawHour, 0, 23)
  if (minute === null || hour === null || month !== "*") return null

  const time = `${pad(hour)}:${pad(minute)} UTC`

  if (dom === "*" && dow === "*") return `每日 ${time}`
  if (dom === "*") {
    const day = parseField(dow, 0, 6)
    return day === null ? null : `每週${WEEKDAYS[day]} ${time}`
  }
  if (dow === "*") {
    const day = parseField(dom, 1, 31)
    return day === null ? null : `每月 ${day} 日 ${time}`
  }
  return null
}
