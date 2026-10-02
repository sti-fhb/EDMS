/**
 * 時間顯示工具。時間一律經此格式化，禁止各處自行 `new Date(...).toLocaleString(...)`。
 *
 * 目前僅提供 US4 需要的 `formatDateTime`（日期 + 時分，本地時區）；其餘格式（僅日期 / 相對時間等）
 * 待實際消費者出現時再補（避免臆測擴充）。
 */

const pad = (n: number): string => String(n).padStart(2, "0")

/** `YYYY-MM-DD` 格式化器，固定台灣時區（`en-CA` 的日期格式即為 `YYYY-MM-DD`）。 */
const taipeiDateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

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
  return taipeiDateFormat.format(new Date())
}

/** `YYYY/MM/DD HH:mm` 格式化器，固定台灣時區。 */
const taipeiDateTimeFormat = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
})

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
  return taipeiDateTimeFormat.format(d)
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
