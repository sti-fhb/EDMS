import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
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
})
