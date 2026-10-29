import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { AttemptOverviewBlock } from "./AttemptOverviewBlock"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { formatDateTime } from "../../utils/date"

describe("AttemptOverviewBlock 交卷時間（#551）", () => {
  it("經 date.ts 格式化，不再是 toLocaleString 的上午／下午與秒數", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    // 預設 fixture：王小明「基本概念測驗」兩次作答，交卷於 2026-04-22T02:12Z、2026-05-02T06:05Z
    await user.click(await screen.findByRole("button", { name: /王小明/ }))
    // 期望值由 formatDateTime 現算，不寫死字面時刻（依執行環境時區換算）
    expect(await screen.findByText(formatDateTime("2026-04-22T02:12:00Z"))).toBeInTheDocument()
    expect(screen.getByText(formatDateTime("2026-05-02T06:05:00Z"))).toBeInTheDocument()
    expect(screen.queryByText(/上午|下午/)).not.toBeInTheDocument()
  })
})

describe("AttemptOverviewBlock 輪次分段（#709）", () => {
  it("要求重測後於新一輪前插分隔列，舊輪標「前一輪」", async () => {
    server.use(
      http.get("/api/et/courses/:courseId/attempt-overview", () =>
        HttpResponse.json({
          students: [
            {
              user_id: "s01",
              user_name: "王小明",
              quizzes: [
                {
                  quiz_id: 1,
                  quiz_name: "基本概念測驗",
                  max_retry: 3,
                  used_attempts: 1,
                  is_passed: false,
                  can_reset: false,
                  attempts: [
                    { attempt_id: 11, attempt_no: 1, submitted_at: "2026-09-30T02:41:00Z", score: "100.00", points_total: 100, is_pass: true },
                    { attempt_id: 12, attempt_no: 2, submitted_at: "2026-10-14T09:04:00Z", score: "25.00", points_total: 100, is_pass: false },
                  ],
                  resets: [{ after_attempt_no: 1, kind: "RETEST", executed_at: "2026-10-14T09:00:00Z" }],
                },
              ],
            },
          ],
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: /王小明/ }))

    expect(await screen.findByText(/教師要求重測（測驗內容已更新）/)).toBeInTheDocument()
    expect(screen.getByRole("row", { name: /第 1 次/ })).toHaveTextContent("前一輪")
    expect(screen.getByRole("row", { name: /第 2 次/ })).not.toHaveTextContent("前一輪")
  })
})

describe("重置鈕的說明（#768 第 1 項）", () => {
  // 原本先看 can_reset：學員符合重置條件、但課程已關閉時，鈕是灰的，說明卻寫「重置後該學員可再作答」
  function mockResettable() {
    server.use(
      http.get("/api/et/courses/:courseId/attempt-overview", () =>
        HttpResponse.json({
          students: [
            {
              user_id: "s01",
              user_name: "王小明",
              quizzes: [
                {
                  quiz_id: 1,
                  quiz_name: "基本概念測驗",
                  max_retry: 0,
                  used_attempts: 1,
                  is_passed: false,
                  can_reset: true,
                  attempts: [
                    { attempt_id: 11, attempt_no: 1, submitted_at: "2026-09-30T02:41:00Z", score: "40.00", points_total: 100, is_pass: false },
                  ],
                  resets: [],
                },
              ],
            },
          ],
        }),
      ),
    )
  }

  async function hoverReset(readOnly: boolean) {
    mockResettable()
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={readOnly} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: /王小明/ }))
    const button = await screen.findByRole("button", { name: "重置重考次數" })
    await user.hover(button.parentElement as HTMLElement)
    return { button, tooltip: await screen.findByRole("tooltip") }
  }

  it("唯讀（課程已關閉）：說明為課程已關閉，不寫「可再作答」", async () => {
    const { button, tooltip } = await hoverReset(true)
    expect(button).toBeDisabled()
    expect(tooltip).toHaveTextContent("課程已關閉，無法重置")
    expect(tooltip).not.toHaveTextContent("重置後該學員可再作答")
  })

  it("可重置且非唯讀：照舊說明「重置後該學員可再作答」（正向錨點）", async () => {
    const { button, tooltip } = await hoverReset(false)
    expect(button).toBeEnabled()
    expect(tooltip).toHaveTextContent("重置後該學員可再作答")
  })
})

describe("AttemptOverviewBlock 多測驗表格欄位對齊（#844）", () => {
  /**
   * 兩個測驗：測驗一有「前一輪」Chip 與輪次分隔列（第一欄被撐寬的來源），測驗二沒有。
   *
   * 🔴 **這個組合就是本 issue 的觸發條件**。兩個內容相同的測驗測不出任何東西——
   * `table-layout: auto` 下它們本來就會一樣寬。
   */
  function twoQuizzes() {
    server.use(
      http.get("/api/et/courses/:courseId/attempt-overview", () =>
        HttpResponse.json({
          students: [
            {
              user_id: "s01",
              user_name: "ET學員乙",
              quizzes: [
                {
                  quiz_id: 1,
                  quiz_name: "測驗一",
                  max_retry: 2,
                  used_attempts: 0,
                  is_passed: false,
                  can_reset: true,
                  // 第一欄會多出「前一輪」Chip
                  attempts: [
                    { attempt_id: 11, attempt_no: 1, submitted_at: "2026-10-21T06:31:00Z", score: "100.00", points_total: 100, is_pass: true },
                  ],
                  // 底下還會多一列「教師要求重測」分隔列
                  resets: [{ after_attempt_no: 1, kind: "RETEST", executed_at: "2026-10-21T06:39:00Z" }],
                },
                {
                  quiz_id: 2,
                  quiz_name: "測驗二",
                  max_retry: 2,
                  used_attempts: 1,
                  is_passed: true,
                  can_reset: true,
                  attempts: [
                    { attempt_id: 21, attempt_no: 1, submitted_at: "2026-10-21T06:31:00Z", score: "100.00", points_total: 100, is_pass: true },
                  ],
                  resets: [],
                },
              ],
            },
          ],
        }),
      ),
    )
  }

  /** 展開學員後取得兩張表的表頭儲存格寬度。 */
  async function headerWidths() {
    const user = userEvent.setup()
    renderWithProviders(<AttemptOverviewBlock courseId={1} readOnly={false} onOpenDetail={vi.fn()} onReset={vi.fn()} />)
    await user.click(await screen.findByRole("button", { name: /ET學員乙/ }))
    await screen.findByText("測驗二")

    const tables = document.querySelectorAll("table")
    expect(tables.length).toBe(2)
    // ⚠️ 讀 `getComputedStyle` 而非 `element.style`：MUI 的 `sx` 編譯成 **CSS class**
    // （`css-xxxx-MuiTable-root`），不是 inline style——讀 `.style.width` 一律是空字串，
    // 而「兩張表都是空字串」會讓 `toEqual` 恆真，是個看起來很綠的假守門。
    return [...tables].map((t) =>
      [...t.querySelectorAll("thead th")].map((th) => getComputedStyle(th as HTMLElement).width),
    )
  }

  it("🔴 兩個測驗的五個欄位都宣告了寬度，且兩張表逐欄相同", async () => {
    // ## ⚠️ 這條驗的是**宣告**，不是排版結果
    //
    // jsdom **不做實際排版**：`getComputedStyle` 回的是宣告值，不會算出「這張表因為
    // 內容較寬所以第一欄 180px、那張 120px」。而 #844 要修的錯位正是排版結果 ⇒
    // **瀏覽器才看得到的東西，測不到**（真要驗得靠 e2e 的視覺比對）。
    //
    // ⇒ 本條改驗可驗證的契約：**五欄都宣告了明確寬度、且兩張表逐欄一致**。這是「欄位
    // 會對齊」的充分條件——`fixed` 版型下，欄寬只由宣告決定，與各表內容無關。
    //
    // 🔴 初版寫成「兩張表的 computed width 相同」，**拿掉任一欄的 width 照樣通過**
    //（兩邊都變 `auto`，`toEqual` 恆真）。⇒ 必須同時斷言「每一欄都有宣告」。
    twoQuizzes()
    const [first, second] = await headerWidths()

    expect(first).toHaveLength(5)
    expect(first).toEqual(second)
    // ⛔ 缺了這行，上面那句在「兩張表都沒宣告寬度」時恆真——而那正是修之前的狀態
    expect(first.every((w) => /^\d+(\.\d+)?%$/.test(w))).toBe(true)
    // 總和應為 100%，否則最後一欄會被瀏覽器自行分配而回到「隨內容跑」
    const total = first.reduce((sum, w) => sum + Number.parseFloat(w), 0)
    expect(total).toBeCloseTo(100, 1)
    // 🔴 **這組是「對齊」的充分條件，但管不到「寬度夠不夠用」**：把某欄改成 5%、其餘
    // 放大，總和仍是 100%，欄位仍對齊——只是內容會折行。那件事 jsdom 驗不到（它不做
    // 排版），由元件註解的寬度推導與手測負責。⛔ 不要以為這條綠了就代表版面沒問題。
  })

  it("表格採 fixed 版型並帶 minWidth（#835 定調的寫法）", async () => {
    // ⚠️ `tableLayout: fixed` 若不搭 `minWidth`，窄螢幕下欄位照樣被擠到讀不了
    //（`ui-design-guide.md` §4：fixed 的表必須搭 minWidth，不可用 width:100%）。
    twoQuizzes()
    await headerWidths()

    const table = document.querySelector("table") as HTMLElement
    const style = getComputedStyle(table)
    expect(style.tableLayout).toBe("fixed")
    const minWidth = Number.parseInt(style.minWidth, 10)
    // ⚠️ 下界不是 `> 0`：那樣把 `minWidth` 改成 1 也會通過，而窄螢幕下欄位照樣被擠爛。
    // 600 是「五欄各自容得下表頭」的粗略底線（實際取 680，推導見元件註解）。
    expect(minWidth).toBeGreaterThanOrEqual(600)
    // guide 的上限：1280 螢幕扣掉側欄
    expect(minWidth).toBeLessThanOrEqual(940)
  })

  it("🔴 輪次分隔列跨滿全部欄位——欄數與 colSpan 是兩處各自寫死的 5", async () => {
    // `RoundDividerRow` 的 `colSpan` 預設 5，而本表剛好五欄；兩個呼叫端
    //（本檔與 ET07 的 `AttemptHistory`）**都不傳**，靠的就是那個預設值。
    //
    // 🔴 #844 把欄數釘成「五個有明確寬度的欄」之後，這個隱性耦合更容易出事：
    // 日後有人加第六欄卻忘了傳 `colSpan`，分隔列會少跨一欄而錯位——而那正是本 issue
    // 要消除的那種錯位，只是換個地方重演。
    //
    // ⇒ 以「分隔列的 colSpan == 表頭欄數」釘住，不依賴任何人記得。
    twoQuizzes()
    await headerWidths()

    const headerCount = document.querySelectorAll("thead th").length / 2 // 兩張表
    const divider = document.querySelector("tbody td[colspan]") as HTMLTableCellElement
    expect(divider).not.toBeNull()
    expect(Number(divider.getAttribute("colspan"))).toBe(headerCount)
  })

  it("⛔ 欄位內容、排序與輪次分隔列一字不改（正向錨點）", async () => {
    twoQuizzes()
    await headerWidths()

    const headers = [...document.querySelectorAll("thead th")].slice(0, 5).map((th) => th.textContent)
    expect(headers).toEqual(["次別", "作答時間", "分數", "是否及格", "明細"])
    // #709 的分隔列與「前一輪」標籤不受版面調整影響
    expect(screen.getByText(/教師要求重測（測驗內容已更新）/)).toBeInTheDocument()
    expect(screen.getAllByText("前一輪")).toHaveLength(1)
    // 分數欄維持右對齊
    // ⚠️ 驗 computed 的 `text-align`，⛔ 不比對 `MuiTableCell-alignRight` 這類**MUI 內部
    // class 名**——那是實作細節，升版改名時會無聲失效（#844 code review LOW）。
    const scoreTh = document.querySelectorAll("thead th")[2] as HTMLElement
    expect(getComputedStyle(scoreTh).textAlign).toBe("right")
  })
})
