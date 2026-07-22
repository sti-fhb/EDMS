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
