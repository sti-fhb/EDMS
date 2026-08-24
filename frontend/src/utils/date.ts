/**
 * 時間顯示工具。時間一律經此格式化，禁止各處自行 `new Date(...).toLocaleString(...)`。
 *
 * 目前僅提供 US4 需要的 `formatDateTime`（日期 + 時分，本地時區）；其餘格式（僅日期 / 相對時間等）
 * 待實際消費者出現時再補（避免臆測擴充）。
 */

const pad = (n: number): string => String(n).padStart(2, "0")

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
