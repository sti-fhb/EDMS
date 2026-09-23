import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, delay, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { EtStudentsPage } from "./StudentsPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 選到預設課程——三個區塊都要先選課程才會渲染。 */
async function selectCourse(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByLabelText("課程"))
  await user.click(await screen.findByRole("option", { name: "採血作業新進人員訓練" }))
}

describe("ET03 學員學習狀況追蹤", () => {
  it("未選課程時三區塊都不渲染", async () => {
    renderWithProviders(<EtStudentsPage />)

    expect(await screen.findByText("請先於右上選擇要檢視的課程。")).toBeInTheDocument()
    expect(screen.queryByText("已加入學員")).not.toBeInTheDocument()
  })

  it("區塊標題不再顯示「區塊 N」編號（#359 第 3 項）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    expect(await screen.findByText("已加入學員")).toBeInTheDocument()
    // ⛔ `spec_us9` 仍稱「區塊 1 / 2 / 3」，但那是**規格內部的條列用語**、不是畫面文字。
    // 手測回饋：教師說的是「作答明細那一塊」，編號對他不構成指稱工具。
    expect(screen.queryByText(/^區塊 [123]$/)).not.toBeInTheDocument()
  })

  it("問卷結果不再標「（母體為在籍學員）」（#359 第 3 項）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    expect(await screen.findByText(/已填 .* 人/)).toBeInTheDocument()
    expect(screen.queryByText(/母體為在籍學員/)).not.toBeInTheDocument()
  })

  it("教師只有草稿課程時，下拉停用並說明原因（#359 第 4 項 AC 3）", async () => {
    // ⚠️ 排除草稿讓這個情境**變得更容易發生**：改之前只有草稿的教師至少看得到自己的課，
    // 改之後下拉是空的——沒有這段說明，他分不出是「沒有課」「還沒發布」還是「壞了」。
    server.use(
      http.get("/api/et/courses", () =>
        HttpResponse.json({
          data: [
            {
              course_id: 21,
              course_name: "只有草稿",
              status: "DRAFT",
              open_start_at: null,
              open_end_at: null,
              owner_id: "t01",
              owner_name: "陳大華",
              tags: [],
              chapter_count: 1,
              student_count: 0,
              is_owner: true,
              is_closed: false,
            },
          ],
          meta: { total: 1, page: 1, limit: 12, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<EtStudentsPage />)

    expect(await screen.findByText("尚無已發布的課程——課程發布後才會有學員")).toBeInTheDocument()
    // MUI 的 select 把 disabled 表現為 combobox 上的 aria-disabled，不是原生 disabled 屬性
    expect(screen.getByLabelText("課程")).toHaveAttribute("aria-disabled", "true")
  })

  it("載入中不得說「尚無已發布的課程」——那時還不知道（#359 第 4 項 AC 3）", async () => {
    // ⚠️ `options` 在載入中也是空的。少了 `coursesPending` 的判斷，慢速連線下教師會看到
    // 一句**假話**——與本 issue 要修的缺陷同一類（畫面告訴使用者一件不成立的事）。
    server.use(
      http.get("/api/et/courses", async () => {
        await delay(200)
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 12, total_pages: 1 } })
      }),
    )
    renderWithProviders(<EtStudentsPage />)

    expect(screen.queryByText(/尚無已發布的課程/)).not.toBeInTheDocument()
    // 載完之後才該出現
    expect(await screen.findByText(/尚無已發布的課程/)).toBeInTheDocument()
  })

  it("課程清單載入失敗時說「載入失敗」，不得說「尚無已發布的課程」（#390 回歸）", async () => {
    // 🔴 #390 自己引入的回歸：該 PR 只讀了 `isPending`，沒讀 `isError`。查詢失敗時
    // `options` 同樣是空的，於是畫面斷言「尚無已發布的課程」——那正是 #390 要修的那一類
    // **假陳述**（畫面告訴使用者一件不成立的事），而且比原本的缺陷更糟：教師會據此
    // 以為「我真的沒有已發布的課程」，而不是「剛才沒載到，重整一下」。
    server.use(http.get("/api/et/courses", () => HttpResponse.json({ detail: "boom" }, { status: 500 })))
    renderWithProviders(<EtStudentsPage />)

    expect(await screen.findByText(/課程清單載入失敗/)).toBeInTheDocument()
    expect(screen.queryByText(/尚無已發布的課程/)).not.toBeInTheDocument()
    // 失敗時也要停用——清單不完整，讓它可展開等於暗示「這就是全部」
    expect(screen.getByLabelText("課程")).toHaveAttribute("aria-disabled", "true")
  })

  it("課程下拉排除草稿、但保留已關閉（#359 第 4 項）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)

    await user.click(await screen.findByLabelText("課程"))

    // 草稿課於發布時才帶入學員，選了只會看到三個空區塊而畫面不說明為什麼
    expect(screen.queryByRole("option", { name: "草稿課" })).not.toBeInTheDocument()
    // ⚠️ 已關閉**必須保留**——ET-11 AC 10：關閉後仍可閱覽學員清單、作答明細與問卷結果，
    // 只是不可再重置／移除。用 `is_closed` 或 `status !== "PUBLISHED"` 過濾會誤殺它。
    expect(screen.getByRole("option", { name: "已關閉的課" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "採血作業新進人員訓練" })).toBeInTheDocument()
  })

  it("選課程後顯示三個區塊", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    expect(await screen.findByText("已加入學員")).toBeInTheDocument()
    expect(await screen.findByText("作答明細")).toBeInTheDocument()
    expect(await screen.findByText("問卷結果")).toBeInTheDocument()
  })

  it("完全未作答者的平均成績顯示破折號而非 0", async () => {
    // 0 分與未作答意義相反——混為一談會讓教師誤判需要輔導的對象
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    const row = (await screen.findByText("李小華")).closest("tr")!
    // 欄序：學員 / 加入日期 / 完課狀態 / 學習進度 / 平均成績 / 最後活動 / 操作
    const avgCell = within(row).getAllByRole("cell")[4]
    expect(avgCell).toHaveTextContent("—")
    expect(avgCell).not.toHaveTextContent("0")
  })

  it("未作答的測驗仍列出並標示「尚未作答」", async () => {
    // 整個測驗不出現的話，教師分不出「他沒考」與「這門課沒這個測驗」
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "王小明" }))

    expect(await screen.findByText("進階測驗")).toBeInTheDocument()
    expect(await screen.findByText("尚未作答")).toBeInTheDocument()
  })

  it("逐題明細顯示學員實際選了什麼（#358 第 1 項）", async () => {
    // 🔴 這條是 #358 的回歸測試。原本前端 `OptionResult` 抄錯了後端欄位名
    // （`option_text` / `is_selected` vs 後端的 `text` / `selected`），於是執行期讀到
    // `undefined`：選項文字全空白、`selected` 為 falsy 故每一題都標成未選——**連滿分的
    // 題目都顯示「（正確答案，未選）」**。
    //
    // 為什麼當初沒被抓到，有兩層：
    //   1. 前端型別是 TypeScript `interface`，只存在於編譯期，執行期不驗證（依
    //      `sti-zod-conventions.md`，API 回應型別本來就保留手寫 interface，不改 zod）
    //   2. **MSW fixture 當時也用前端的錯名字**，假資料與 bug 互相印證；而唯一會開啟
    //      本對話框的測試又把 `questions` 覆寫成 `[]`，那些選項從來沒被渲染過
    //
    // 所以本測試刻意**不覆寫 handler**，走預設 fixture（已對齊後端欄位名）真的渲染選項。
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "王小明" }))
    await user.click(await screen.findByText("第 1 次"))

    // 選對 → 已勾選；fixture 的 Q1 選項 1 是 selected + correct
    expect(await screen.findByText(/☑ 捐血人身分/)).toBeInTheDocument()
    // 未選且非正解 → 未勾選、且不該有「正確答案」字樣
    expect(screen.getByText(/☐ 天氣/)).toBeInTheDocument()
    // 🔴 漏選的正確答案才顯示這句；Q1 全對，所以「捐血人身分」不可帶它
    expect(screen.getByText(/☑ 捐血人身分/)).not.toHaveTextContent("正確答案，未選")
    // Q2 的「消毒」是正解但沒選 → 這才是該顯示的那一個
    expect(screen.getByText(/☐ 消毒（正確答案，未選）/)).toBeInTheDocument()
  })

  it("點歷次作答開啟逐題明細，走的是教師端端點", async () => {
    const spy = vi.fn()
    server.use(
      http.get("/api/et/attempts/:attemptId/detail", ({ params }) => {
        spy(params.attemptId)
        return HttpResponse.json({
          attempt_id: 11,
          user_id: "s01",
          user_name: "王小明",
          quiz_name: "基本概念測驗",
          attempt_no: 1,
          submitted_at: "2026-04-22T02:12:00Z",
          score: "65.00",
          points_total: 100,
          pass_score: 80,
          is_pass: false,
          questions: [],
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "王小明" }))
    await user.click(await screen.findByText("第 1 次"))

    await waitFor(() => expect(spy).toHaveBeenCalledWith("11"))
  })

  it("統計檢視的問答題只顯示已答人數，文字在明細", async () => {
    // 2026-08-28 裁示：長短不一的文字會把單選題的分布擠到看不見
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    expect(await screen.findByText(/問答題 — 已答 1 人/)).toBeInTheDocument()
    expect(screen.queryByText("希望多一點實作")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "明細" }))

    expect(await screen.findByText("希望多一點實作")).toBeInTheDocument()
  })

  it("課程無問卷時整個區塊不渲染", async () => {
    // AC 11 明訂隱藏——顯示「尚無問卷」會讓教師以為自己該去建一份，而問卷是選配
    server.use(
      http.get("/api/et/courses/:courseId/survey-result", () =>
        HttpResponse.json({
          has_survey: false,
          survey_name: null,
          filled_count: 0,
          not_filled_count: 0,
          questions: [],
          details: [],
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    await screen.findByText("已加入學員")
    expect(screen.queryByText("問卷結果")).not.toBeInTheDocument()
  })

  it("重置需二次確認，且成功後顯示提示", async () => {
    const spy = vi.fn()
    server.use(
      http.post("/api/et/courses/:courseId/students/:userId/quizzes/:quizId/retry-reset", () => {
        spy()
        return HttpResponse.json({ user_id: "s01", quiz_id: 1, used_attempts: 0 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "王小明" }))
    // 該學員有兩個測驗 → 兩顆按鈕；取 fixture 中 can_reset=true 的第一顆
    const resetButtons = await screen.findAllByRole("button", { name: /重置重考次數/ })
    await user.click(resetButtons[0])

    // 確認框出現前不可送出——重置是不可逆的破例動作
    expect(spy).not.toHaveBeenCalled()
    expect(await screen.findByText(/確定重置 王小明/)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "確定" }))

    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(await screen.findByText("已重置重考次數")).toBeInTheDocument()
  })

  it("不可重置時按鈕停用", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "王小明" }))

    const buttons = await screen.findAllByRole("button", { name: /重置重考次數/ })
    // fixture：第一個測驗 can_reset=true、第二個 false（未作答）
    expect(buttons[0]).toBeEnabled()
    expect(buttons[1]).toBeDisabled()
  })

  it("課程已關閉時停用管理動作，並說明原因與下一步", async () => {
    // 🔴 ET-16 未實作，期間已過的課程 status 仍是 PUBLISHED——不說明的話，教師看到的
    // 是一門標著「已發布」的課程卻什麼都不能點，那在他眼中是「系統壞了」
    server.use(
      http.get("/api/et/courses", () =>
        HttpResponse.json({
          data: [
            {
              course_id: 11,
              course_name: "採血作業新進人員訓練",
              status: "PUBLISHED",
              open_start_at: null,
              open_end_at: "2026-01-01T00:00:00Z",
              owner_id: "t01",
              owner_name: "陳大華",
              tags: [],
              chapter_count: 1,
              student_count: 2,
              is_owner: true,
              is_closed: true,
            },
          ],
          meta: { total: 1, page: 1, limit: 100, total_pages: 1 },
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    expect(await screen.findByText(/目前為/)).toBeInTheDocument()
    expect(screen.getByText(/再開課/)).toBeInTheDocument()
    const removeButtons = await screen.findAllByRole("button", { name: /移除/ })
    expect(removeButtons[0]).toBeDisabled()
  })

  it("課程已關閉仍可閱覽與匯出", async () => {
    // AC 10：關閉只停寫入（#255 裁示 Q2=A「讀照舊、寫全停」）
    server.use(
      http.get("/api/et/courses", () =>
        HttpResponse.json({
          data: [
            {
              course_id: 11,
              course_name: "採血作業新進人員訓練",
              status: "CLOSED",
              open_start_at: null,
              open_end_at: null,
              owner_id: "t01",
              owner_name: "陳大華",
              tags: [],
              chapter_count: 1,
              student_count: 2,
              is_owner: true,
              is_closed: true,
            },
          ],
          meta: { total: 1, page: 1, limit: 100, total_pages: 1 },
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    const rows = await screen.findAllByText("王小明")
    expect(rows.length).toBeGreaterThan(0)
    const exports = screen.getAllByRole("button", { name: /匯出 CSV/ })
    expect(exports[0]).toBeEnabled()
  })

  it("匯出是按鈕而非連結——連結帶不出 Bearer token", async () => {
    // 🔴 本專案的 access token 是 memory-only Bearer，只在 axios 的 request interceptor
    // 注入；後端用 HTTPBearer、全站沒有 cookie 認證。`<a href="/api/...">` 是瀏覽器原生
    // 導覽，不經 axios、不帶 header——那樣的匯出會直接 401。
    //
    // ⚠️ 這條斷言的是 **role**，因為那是 href 與 onClick 唯一在 DOM 上分得出來的差別。
    // 原本的測試寫 `getAllByRole("link")` 且只檢查 enabled，所以它對 401 完全無感——
    // 一個永遠失敗的連結，在畫面上與正常的一模一樣。
    //
    // 修法照 `dm/kpi/kpiService.ts` 的 `downloadKpiCsv`（DM 三處匯出皆同一寫法）。
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await screen.findAllByText("王小明")

    const exports = screen.getAllByRole("button", { name: /匯出 CSV/ })
    expect(exports.length).toBeGreaterThanOrEqual(2) // 區塊 1 與區塊 3 各一
    for (const button of exports) {
      expect(button).not.toHaveAttribute("href")
    }
    expect(screen.queryAllByRole("link", { name: /匯出 CSV/ })).toHaveLength(0)
  })

  it("匯出成功要有提示——瀏覽器下載是無聲的", async () => {
    // ET-MSG-ET03-007。檔案落到下載資料夾、頁面完全沒有變化，少了這則提示，教師
    // 按下匯出後唯一的回饋是「什麼都沒發生」，於是再按一次。
    //
    // jsdom 沒有實作 `URL.createObjectURL`，不補的話成功路徑會拋 TypeError 被 catch
    // 接走——那樣這條測試會變成在驗錯誤處理，而且是綠的。
    //
    // ⚠️ **只補這兩個方法，不要 `vi.stubGlobal("URL", {...URL})`**：`URL` 是 class，
    // 展開不會帶到靜態方法，換掉整個 global 會讓 MSW 與 axios 解析不了網址，後面每一條
    // 測試的課程下拉都會變成空的——而且失敗訊息指向 `selectCourse`，看起來像別的 bug。
    const createObjectURL = vi.fn(() => "blob:mock")
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })

    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await screen.findAllByText("王小明")

    await user.click(screen.getAllByRole("button", { name: /匯出 CSV/ })[0])

    expect(await screen.findByText("CSV 已匯出")).toBeInTheDocument()
    expect(createObjectURL).toHaveBeenCalledOnce()
  })

  it("移除作答中的學員才跳警告，一般學員不跳", async () => {
    // AC 7 / ET-MSG-ET03-003。原先兩種情況合用一句「該學員**若**正在作答……」，
    // 把警告稀釋成每次都出現的免責聲明——每次都出現的警告等於沒有警告。
    //
    // fixture 裡 s01 王小明 `has_in_progress_attempt: false`、s02 李小華 `true`，
    // 同一條測試驗兩邊，避免只驗到其中一種而誤以為分支有效。
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await screen.findAllByText("王小明")

    // 用 regex：按鈕文字是「移除」，但外層 Tooltip 的 title 會參與可及名稱計算，
    // 精確比對 "移除" 會找不到。
    const removes = screen.getAllByRole("button", { name: /移除/ })

    // 王小明（沒有作答中的考卷）→ 一般確認，不是 alert
    await user.click(removes[0])
    const plain = await screen.findByRole("dialog")
    expect(within(plain).getByText(/確定移除 王小明/)).toBeInTheDocument()
    expect(within(plain).queryByRole("alert")).not.toBeInTheDocument()
    await user.click(within(plain).getByRole("button", { name: "取消" }))
    // Dialog 開著時 MUI 會把背景設 `aria-hidden`，收合動畫跑完前表格的按鈕不在可及性
    // 樹裡——不等它消失就再查，會得到「找不到移除按鈕」這種指向錯方向的失敗。
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())

    // 李小華（作答中）→ 警告版，且文案要講明 attempt 會保留
    await user.click(screen.getAllByRole("button", { name: /移除/ })[1])
    const warned = await screen.findByRole("dialog")
    const alert = within(warned).getByRole("alert")
    expect(alert).toHaveTextContent("李小華作答中")
    expect(alert).toHaveTextContent("保留並計入歷史")
  })

  it("沒有分頁列——待加入已隨 #362 移除，選好課程就直接看到三區塊", async () => {
    // 原本這裡有三條測試釘「待加入」分頁（清單、撤回二次確認、關閉時重寄禁用但撤回可用，
    // 含 2026-09-16 那條 SA 裁示）。功能整組移除後它們釘的規則不再存在，故刪除而非改寫。
    //
    // 留下這一條反向斷言：日後若有人把 tab 加回來（例如為了塞別的清單），
    // 「教師要多點一下才看得到學員」這個回歸會被抓到。
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    // 等區塊真的載完再斷言「沒有 tab」——否則畫面還在載入時查不到 tab 也會通過。
    // 用區塊標題而非學員姓名：同一個姓名在「已加入學員」與「作答明細」兩區都出現。
    expect(await screen.findByText("已加入學員")).toBeInTheDocument()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByText("待加入")).not.toBeInTheDocument()
  })

  // ── US16 線下考核核可（#352）──────────────────────────────────────────────

  /** 覆寫學員清單為「已啟用線下核可」的課程。 */
  function withApproval(rows: Record<string, unknown>[]) {
    server.use(
      http.get("/api/et/courses/:courseId/students", () =>
        HttpResponse.json({ data: rows, meta: { total: rows.length, page: 1, limit: 20, total_pages: 1 } }),
      ),
    )
  }

  /** 覆寫課程清單為「閱課期間已過」——`is_closed` 由後端算，前端不自己判 status。 */
  function withClosedCourse() {
    server.use(
      http.get("/api/et/courses", () =>
        HttpResponse.json({
          data: [
            {
              course_id: 1,
              course_name: "採血作業新進人員訓練",
              status: "PUBLISHED",
              open_start_at: null,
              open_end_at: "2026-01-01T00:00:00Z",
              owner_id: "t01",
              owner_name: "陳大華",
              tags: [],
              chapter_count: 1,
              student_count: 2,
              is_owner: true,
              is_closed: true,
            },
          ],
          meta: { total: 1, page: 1, limit: 100, total_pages: 1 },
        }),
      ),
    )
  }

  const baseRow = {
    joined_at: "2026-04-01T02:00:00Z",
    completion_status: "COMPLETED",
    progress_pct: 100,
    avg_score: "88.50",
    last_activity_at: "2026-05-02T06:30:00Z",
    has_in_progress_attempt: false,
    approval_note: null,
    approved_by_name: null,
    approved_at: null,
    approval_version: null,
  }

  it("未啟用線下核可的課程完全不顯示核可欄與工具列", async () => {
    // 預設 handler 的兩列 approval_status 皆為 null（REQUIRE_APPROVAL = false）
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    // ⚠️ 用「李小華」而非「王小明」——後者同時出現在區塊 2 的作答明細，
    // `findByText` 會抓到多個而拋錯（不是元件壞了）。
    await screen.findByText("李小華")

    expect(screen.queryByText("核可狀態")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "批次核可通過" })).not.toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: "全選本頁待核可學員" })).not.toBeInTheDocument()
  })

  it("啟用核可時待核可者可勾選、未達核可資格者的勾選框停用", async () => {
    // 🔴 未完課者在 UI 就擋掉——後端仍會跳過，但教師不該按了才知道
    withApproval([
      { ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PENDING" },
      {
        ...baseRow,
        user_id: "s02",
        user_name: "李小華",
        completion_status: "IN_PROGRESS",
        progress_pct: 75,
        approval_status: "NOT_ELIGIBLE",
      },
    ])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await screen.findByText("核可狀態")

    expect(screen.getByText("未達核可資格")).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "選取 王小明" })).toBeEnabled()
    expect(screen.getByRole("checkbox", { name: "選取 李小華" })).toBeDisabled()
  })

  it("已有核可結果者只給撤銷，不給直接改判", async () => {
    // wireframe 行 1358：已通過的列只有「撤銷」。允許直接點「不通過」等於繞過
    // 「撤銷須填原因」（FR-ET-US16-06）
    withApproval([
      {
        ...baseRow,
        user_id: "s01",
        // 刻意不用「王小明」——區塊 2 的作答明細也有同名按鈕，`findByText` 會抓到多個
        user_name: "陳受訓",
        approval_status: "PASSED",
        approved_by_name: "王主任",
        approved_at: "2026-05-19T01:00:00Z",
        approval_version: 1,
      },
    ])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    const row = (await screen.findByText("陳受訓")).closest("tr")!

    expect(within(row).getByRole("button", { name: "撤銷" })).toBeInTheDocument()
    expect(within(row).queryByRole("button", { name: "通過" })).not.toBeInTheDocument()
    expect(within(row).queryByRole("button", { name: "不通過" })).not.toBeInTheDocument()
    expect(within(row).getByText(/王主任 核可/)).toBeInTheDocument()
  })

  it("撤銷原因未填時 inline 擋下且不送出請求", async () => {
    // ET-MSG-ET03-305。錯誤掛在那個輸入框上，不是飄到畫面角落的 Snackbar
    const spy = vi.fn()
    server.use(
      http.post("/api/et/courses/:courseId/approvals/:userId/revoke", () => {
        spy()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    withApproval([
      { ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PASSED", approval_version: 3 },
    ])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "撤銷" }))
    await user.click(await screen.findByRole("button", { name: "確定" }))

    expect(await screen.findByText("請填寫撤銷原因")).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })

  it("撤銷帶回原樣的 version 與去空白後的原因", async () => {
    const spy = vi.fn()
    server.use(
      http.post("/api/et/courses/:courseId/approvals/:userId/revoke", async ({ request }) => {
        spy(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )
    withApproval([
      { ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PASSED", approval_version: 3 },
    ])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "撤銷" }))
    await user.type(await screen.findByLabelText(/撤銷原因/), "  考核紀錄登錄錯誤  ")
    await user.click(screen.getByRole("button", { name: "確定" }))

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ reason: "考核紀錄登錄錯誤", version: 3 }))
  })

  it("單筆核可全部被跳過時顯示錯誤而非成功", async () => {
    // 🔴 後端回 200 + approved=0。只看狀態碼就報「已完成核可」會讓教師以為寫進去了
    server.use(
      http.post("/api/et/courses/:courseId/approvals", () =>
        HttpResponse.json({ approved: 0, skipped: [{ user_id: "s01", reason: "NOT_COMPLETED" }] }),
      ),
    )
    withApproval([{ ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PENDING" }])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("button", { name: "通過" }))
    await user.click(await screen.findByRole("button", { name: "確定" }))

    // ET-MSG-ET03-304
    expect(await screen.findByText("學員尚未完課，無法核可")).toBeInTheDocument()
    expect(screen.queryByText("已完成核可")).not.toBeInTheDocument()
  })

  it("批次部分成功時逐理由列出跳過筆數", async () => {
    // 兩種跳過對教師的下一步不同（等他完課 vs 先撤銷），壓成一句他不知道該做什麼
    server.use(
      http.post("/api/et/courses/:courseId/approvals", () =>
        HttpResponse.json({
          approved: 1,
          skipped: [
            { user_id: "s02", reason: "NOT_COMPLETED" },
            { user_id: "s03", reason: "ALREADY_APPROVED" },
          ],
        }),
      ),
    )
    withApproval([
      { ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PENDING" },
      { ...baseRow, user_id: "s02", user_name: "李小華", approval_status: "PENDING" },
    ])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    // #415 起表頭沒有全選鈕，教師逐一勾選
    await user.click(await screen.findByRole("checkbox", { name: "選取 王小明" }))
    await user.click(screen.getByRole("checkbox", { name: "選取 李小華" }))
    await user.click(screen.getByRole("button", { name: "批次核可通過" }))
    await user.click(await screen.findByRole("button", { name: "確定" }))

    expect(await screen.findByText(/已核可 1 筆/)).toBeInTheDocument()
    expect(screen.getByText(/尚未完課（1 筆）/)).toBeInTheDocument()
    expect(screen.getByText(/已有核可紀錄（1 筆）/)).toBeInTheDocument()
  })

  it("不通過的確認框有備註欄，通過的沒有", async () => {
    // FR-ET-US16-04：FAIL 得附備註。PASS 顯示備註欄只會在 DB 留一堆空備註
    withApproval([{ ...baseRow, user_id: "s01", user_name: "王小明", approval_status: "PENDING" }])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)

    await user.click(await screen.findByRole("button", { name: "通過" }))
    expect(await screen.findByText(/確定核可王小明為「通過」/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/備註/)).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "取消" }))
    await user.click(await screen.findByRole("button", { name: "不通過" }))
    expect(await screen.findByLabelText(/備註/)).toBeInTheDocument()
  })

  it("換頁後清空勾選，工具列回到停用而不會送出空名單", async () => {
    // 🔴 `selected` 是純 id 的 Set，真正送出的名單是 `rows.filter(...)`——只認本頁。
    // 不清的話：第 1 頁勾人 → 翻頁 → `selected.size` 仍非零（按鈕還亮著），但
    // `selectedRows` 是空的，按下去會送出空 user_ids → 後端 422，教師看到一個對不上
    // 任何操作的錯誤。
    const spy = vi.fn()
    server.use(
      http.post("/api/et/courses/:courseId/approvals", () => {
        spy()
        return HttpResponse.json({ approved: 1, skipped: [] })
      }),
      http.get("/api/et/courses/:courseId/students", ({ request }) => {
        const page = new URL(request.url).searchParams.get("page") ?? "1"
        const row =
          page === "1"
            ? { ...baseRow, user_id: "s01", user_name: "第一頁學員", approval_status: "PENDING" }
            : { ...baseRow, user_id: "s02", user_name: "第二頁學員", approval_status: "NOT_ELIGIBLE" }
        return HttpResponse.json({ data: [row], meta: { total: 2, page: Number(page), limit: 20, total_pages: 2 } })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await user.click(await screen.findByRole("checkbox", { name: "選取 第一頁學員" }))
    expect(screen.getByRole("button", { name: "批次核可通過" })).toBeEnabled()

    await user.click(screen.getByRole("button", { name: "Go to page 2" }))
    await screen.findByText("第二頁學員")

    expect(screen.getByRole("button", { name: "批次核可通過" })).toBeDisabled()
    expect(spy).not.toHaveBeenCalled()

    // 🔴 這一段釘的是**清空**本身，上面那段其實只驗到 `disabled` 改看 `selectedRows`
    // 那一半的修正（換頁後本頁沒人被勾，按鈕本來就會停用）。
    //
    // 回到第 1 頁時勾選框必須是**未勾**的。若 `selected` 沒被清空，它會維持勾選，而
    // 那正是「在第 2 頁按全選會無聲蓋掉第 1 頁選取」那條路徑的前提。
    await user.click(screen.getByRole("button", { name: "Go to page 1" }))
    await screen.findByText("第一頁學員")

    expect(screen.getByRole("checkbox", { name: "選取 第一頁學員" })).not.toBeChecked()
  })

  it("課程已關閉時核可與批次全部停用但狀態照常顯示", async () => {
    // AC 12「讀照舊、寫全停」——狀態欄不可跟著消失，那是閱覽內容
    withClosedCourse()
    withApproval([{ ...baseRow, user_id: "s01", user_name: "陳受訓", approval_status: "PENDING" }])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    const row = (await screen.findByText("陳受訓")).closest("tr")!

    expect(within(row).getByText("待核可")).toBeInTheDocument()
    expect(within(row).getByRole("button", { name: "通過" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "批次核可通過" })).toBeDisabled()
    expect(screen.getByRole("checkbox", { name: "選取 陳受訓" })).toBeDisabled()
  })

  it("表頭沒有全選勾選框（#415）", async () => {
    withApproval([{ ...baseRow, user_id: "s01", user_name: "陳受訓", approval_status: "PENDING" }])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    await screen.findByText("陳受訓")

    expect(screen.queryByRole("checkbox", { name: /全選/ })).not.toBeInTheDocument()
    // 逐列的勾選框不受影響——批次核可仍靠它
    expect(screen.getByRole("checkbox", { name: "選取 陳受訓" })).toBeInTheDocument()
  })

  it("核可與移除分屬兩欄，移除不與不通過相鄰（#415）", async () => {
    // 🔴 兩者的後果差距極大：一個是判定未通過，一個是把人踢出課程。
    withApproval([{ ...baseRow, user_id: "s01", user_name: "陳受訓", approval_status: "PENDING" }])
    const user = userEvent.setup()
    renderWithProviders(<EtStudentsPage />)
    await selectCourse(user)
    const row = (await screen.findByText("陳受訓")).closest("tr")!

    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent ?? "")
    expect(headers).toContain("核可")
    expect(headers).toContain("操作")

    const cells = within(row).getAllByRole("cell")
    const approvalCell = cells[headers.indexOf("核可")]
    const actionCell = cells[headers.indexOf("操作")]
    expect(within(approvalCell).getByRole("button", { name: "通過" })).toBeInTheDocument()
    expect(within(approvalCell).getByRole("button", { name: "不通過" })).toBeInTheDocument()
    expect(within(approvalCell).queryByRole("button", { name: "移除" })).not.toBeInTheDocument()
    expect(within(actionCell).getByRole("button", { name: "移除" })).toBeInTheDocument()
  })
})
