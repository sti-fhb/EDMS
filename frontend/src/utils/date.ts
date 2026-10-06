/**
 * 時間顯示工具。時間一律經此格式化，禁止各處自行 `new Date(...).toLocaleString(...)`，
 * 也禁止以 `.slice(0, 10)` 等字串截取取日期（後端回傳 UTC，見 `formatDateTaipei`）。
 *
 * 各函式之用途與選用時機見其 JSDoc，以及 `.claude/rules/sti-frontend-modules.md`〈date.ts〉的對照表；
 * 新增函式時兩處同步更新。
 */

const pad = (n: number): string => String(n).padStart(2, "0")

/**
 * 台灣時區的年月日時分，**取 parts 而非組好的字串**。
 *
 * ⚠️ 不可改用 `.format()` 的輸出直接當結果：各段之間的分隔字元由 ICU 的 locale 資料決定，
 * **同一段程式在不同 Node / 瀏覽器的 ICU 版本下會給出不同的空白字元**。本機（Node 22）在日期與
 * 時間之間給 ASCII 空格，GitHub CI 的 Node 給的卻不是，於是 `toBe("2026/10/01 07:30")` 兩邊字串
 * 「看起來一模一樣」卻不相等——本機全綠、CI 紅（#483）。自行以字面量拼接後就不受環境影響。
 *
 * `hourCycle: "h23"` 而非 `hour12: false`：後者在部分 locale 的午夜會給 `24`。
 */
const taipeiPartsFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
})

/** 取台灣時間的各段數值（`year` / `month` / `day` / `hour` / `minute`，皆為補零字串）。 */
function taipeiParts(date: Date): Record<string, string> {
  const parts: Record<string, string> = {}
  for (const { type, value } of taipeiPartsFormat.formatToParts(date)) parts[type] = value
  return parts
}

/**
 * 今天的日期（`YYYY-MM-DD`，**台灣時間**）；供 `<input type="date">` 的 min / max 使用。
 *
 * ⚠️ 不可用 `new Date().toISOString().slice(0, 10)`：那是 **UTC** 的日期，台灣時間早上 8 點前
 * 會回「昨天」，日期選擇器的上限因此停在昨天、使用者選不到今天（#483 第 2 項；DM01 / DM03 /
 * DM05 三頁原本各自複製了一份這種寫法）。
 *
 * 時區固定為 `Asia/Taipei` 而非瀏覽器本地時區：後端的日界也釘在台灣時間
 * （`app/core/db.py::create_app_engine`），兩端用同一個基準才不會在使用者機器時區不同時錯開。
 */
export function todayTaipei(): string {
  const p = taipeiParts(new Date())
  return `${p.year}-${p.month}-${p.day}`
}

/**
 * 格式化為 `YYYY/MM/DD HH:mm`（**台灣時間**）；null / 空 / 非法值回 `—`。
 *
 * 供**稽核導向**畫面使用（DM03 已廢止文件查詢、DM05 文件變更歷程）：這兩頁的日期篩選由後端以
 * 台灣時間切日（`app/core/db.py::create_app_engine`）、匯出的 CSV 也以台灣時間呈現
 * （`app/core/utils.py::format_taipei`），畫面若跟著瀏覽器時區走，對不在台灣時區的稽核人員
 * 就會「篩 10/01 撈出來的那筆，畫面顯示 09/30」（#483）。
 *
 * 其餘畫面仍用 `formatDateTime`（瀏覽器時區）。兩者在台灣境內結果相同。
 */
export function formatDateTimeTaipei(value: string | null | undefined): string {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "—"
  const p = taipeiParts(d)
  return `${p.year}/${p.month}/${p.day} ${p.hour}:${p.minute}`
}

/**
 * 只取日期 `YYYY-MM-DD`（**台灣時間**）；null / 空 / 非法值回 `—`。供清單與詳細頁中只顯示日期的欄位。
 *
 * ⚠️ 不可用 `value.slice(0, 10)`：後端回傳的是 UTC（`…Z`），截取得到的是 **UTC 的日期**，
 * 台灣時間 00:00–08:00 發生的事會顯示成前一天（#539；原本 DP02 / DM00–DM08 共 9 處如此）。
 *
 * 分隔用 `-` 而非 `formatDateTimeTaipei` 的 `/`：沿用這些欄位改版前的呈現，並與 `todayTaipei` 同格式。
 */
export function formatDateTaipei(value: string | null | undefined): string {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "—"
  const p = taipeiParts(d)
  return `${p.year}-${p.month}-${p.day}`
}

/** 格式化為 `YYYY/MM/DD HH:mm`（本地時區）；null / 空 / 非法值回 `—`。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "—"
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * ISO 8601（後端回傳，帶時區）→ `<input type="datetime-local">` 需要的
 * `YYYY-MM-DDTHH:mm`（**本地時區的牆上時間**）。
 *
 * ⚠️ 不可用 `iso.slice(0, 16)`：那是把 UTC 字串直接當本地時間顯示，會差一個時區偏移
 * （台灣 +8 即差 8 小時）。必須真的做時區換算。
 */
export function toDateTimeLocalInput(value: string | null | undefined): string {
  if (!value) return ""
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ""
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * `<input type="datetime-local">` 的值（本地牆上時間、無時區）→ ISO 8601 UTC。
 *
 * ⚠️ 不可原樣送出：後端欄位為 `TIMESTAMPTZ`，收到 naive 值會以連線時區解讀而靜默位移，
 * 使「起始時間前學員不可見」「到期自動關閉」等時間判定算錯。
 */
export function fromDateTimeLocalInput(value: string): string | null {
  if (!value) return null
  const d = new Date(value) // 無時區字串由 JS 以**本地時區**解析，正是所需語意
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}
