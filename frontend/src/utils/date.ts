/**
 * 時間顯示工具。時間一律經此格式化，禁止各處自行 `new Date(...).toLocaleString(...)`，
 * 也禁止以 `.slice(0, 10)` 等字串截取取日期（後端回傳 UTC，見 `formatDateTaipei`）。
 *
 * ## 選哪一支：三層規則（#559）
 *
 * 依序判斷，命中即停：
 *
 * 1. **只顯示日期**（`YYYY-MM-DD`）→ `formatDateTaipei`。一律台灣時間，**與下面兩層無關**：
 *    截取 UTC 字串在任何畫面都是錯的（#539）。
 * 2. **日期＋時刻，且讀者會拿它對照「以台灣日界切日的日期篩選」結果** → `formatDateTimeTaipei`。
 *    後端篩選以台灣時間切日（`app/core/db.py::create_app_engine`），時刻欄若跟著瀏覽器時區走，
 *    電腦時區設錯時會出現「篩 10/01 撈出來的那筆，畫面顯示 09/30」（#483）。判法：
 *    - **欄位所在的畫面有這種日期篩選** → 算，**不論被篩的是不是這一欄**：讀者分不出清單上
 *      哪一欄是被篩的那一欄，同一張清單上的時刻必須和篩選同一基準。
 *    - **欄位在可由上述畫面點進去的明細／詳細頁** → 也算：讀者帶著篩選條件點進來核對。
 *      篩選在前一頁、不在明細頁上也一樣。一個元件被多個入口共用時，**任一入口符合即算**
 *      ——元件不知道自己從哪進來，畫面只能有一種寫法。
 *    - **只有 CSV 匯出、沒有日期篩選 → 不算**，歸第 3 層（2026-10-07 裁示，見下方 ET02）。
 * 3. **其餘日期＋時刻** → `formatDateTime`（瀏覽器時區）。
 *
 * 在台灣時區的電腦上，2、3 兩層輸出一字不差；差別只在電腦時區設錯時才顯現。
 *
 * ### 第 2 層的成員與理由（盤點須與實際使用 `formatDateTimeTaipei` 的檔案一致）
 *
 * | 畫面 | 檔案 | 理由 |
 * |---|---|---|
 * | DM03 已廢止文件查詢 | `dm/obsolete/DmObsoletePage.tsx` | 廢止日期篩選以台灣日界 |
 * | DM05 文件變更歷程查詢 | `dm/changelog/DmChangeLogPage.tsx` | 異動日期篩選以台灣日界 |
 * | DP05 操作記錄查詢 | `dp/audit/AuditPage.tsx`、`AuditDetailDialog.tsx` | 起訖日期篩選以台灣日界（#519） |
 * | DM07 文件詳細頁 | `dm/detail/DmDetailPage.tsx` | 本身無篩選，但可由 DM03 點入：DM03 點列導向 `/dm/documents/:docId`（`DmObsoletePage.tsx`），與文件庫進入的是同一條路由、同一個元件（`router.tsx`）→ 明細頁、任一入口符合 |
 *
 * 驗法：`grep -rl formatDateTimeTaipei frontend/src --include=*.tsx | grep -v '\.test\.'` 的每個檔案
 * 都要出現在上表；新增成員時兩處同步。
 *
 * ### 看起來可疑、但判定正確的例子（照上述規則應推導出相同結論）
 *
 * - **ET02 學員學習表現**：有台灣時間的 CSV 匯出，但**沒有日期篩選** → 第 3 層。
 *   「匯出也算」的寫法於 2026-10-07 評估後未採用（#559）：畫面與 CSV 的差異只在電腦時區設錯、
 *   且有人逐筆比對時才會出現，不足以推翻 #551 的裁示。
 * - **DP02 權限管理**：同頁「最後異動」用 `formatDateTaipei`、「鎖定至」用 `formatDateTime`。
 *   前者只有日期（第 1 層）、後者是時刻且該頁無日期篩選（第 3 層），不是混用。
 * - **DP06 排程總覽**：「執行時點」固定台灣時間是 cron 定義的語意（見 `dp/schedules/cron.ts`），
 *   「最近執行／下次執行」走第 3 層。⛔ 不要為了「同列一致」去改，理由見 cron.ts（#517）。
 *
 * 各函式的細節見其 JSDoc；`.claude/rules/sti-frontend-modules.md`〈date.ts〉有同一份對照表，
 * 規則或成員異動時兩處同步更新。
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
 * 三層規則的**第 2 層**：所在畫面有以台灣日界切日的日期篩選（含共用同一元件的延伸頁）。
 * 適用畫面與理由見本檔檔頭的表格——那份表格是判斷依據，⛔ 不要只看這裡就決定。
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

/**
 * 格式化為 `YYYY/MM/DD HH:mm`（**瀏覽器本地時區**）；null / 空 / 非法值回 `—`。
 *
 * 三層規則的**第 3 層**：日期＋時刻、且所在畫面沒有台灣日界的日期篩選（見本檔檔頭）。
 */
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
