/**
 * 測驗流程的**瀏覽歷程形狀**（#549）——以真的 router 跑完整段，不 mock `useNavigate`。
 *
 * 其他測驗元件的測試都 mock 掉 `useNavigate`，只能驗「呼叫了什麼」；而 #549 是歷程的
 * **形狀**錯了（四次 push 疊出 `[my-courses, learn, attempt, result, learn?quiz]`），
 * 必須讓 router 真的記下歷程，再按返回看落在哪裡。
 *
 * 學習頁以一個只渲染 `QuizIntroPanel` 的替身代替：真正的 `LearnPage` 要整套課程結構，
 * 而本檔驗的是測驗三頁之間的導覽，不是學習頁怎麼選項目（那由 `LearnPage.test` 負責）。
 */
import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { RouterProvider, createMemoryRouter, useLocation } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { QuizIntroPanel } from "./QuizIntroPanel"
import { useGoBack } from "../../hooks/useGoBack"
import { EtQuizAnswerPage } from "./QuizAnswerPage"
import { EtQuizResultPage } from "./QuizResultPage"
import { NotificationProvider } from "../../contexts/NotificationContext"
import { muiTheme } from "../../styles/muiTheme"

/**
 * 學習頁替身：顯示目前網址（含 search）、返回鍵與測驗面板（fixture 的 quiz_id = 700）。
 * 返回鍵與真正的 `LearnPage` 相同：`useGoBack("/et/my-courses")`。
 */
function LearnStub() {
  const { pathname, search } = useLocation()
  const goBack = useGoBack("/et/my-courses")
  return (
    <div>
      <button type="button" onClick={goBack}>
        學習頁返回
      </button>
      <p data-testid="learn-url">{pathname + search}</p>
      <QuizIntroPanel quizId={700} />
    </div>
  )
}

function renderFlow(initialEntries: string[]) {
  const router = createMemoryRouter(
    [
      { path: "/et/my-courses", element: <p>我的課程頁</p> },
      { path: "/et/courses/:courseId/learn", element: <LearnStub /> },
      { path: "/et/attempts/:attemptId", element: <EtQuizAnswerPage /> },
      { path: "/et/attempts/:attemptId/result", element: <EtQuizResultPage /> },
    ],
    { initialEntries, initialIndex: initialEntries.length - 1 },
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <NotificationProvider>
          <RouterProvider router={router} />
        </NotificationProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  return router
}

const path = (router: ReturnType<typeof renderFlow>) =>
  router.state.location.pathname + router.state.location.search

describe("測驗流程只佔一個歷程格（#549）", () => {
  it("作答 → 提交 → 結果 → 回課程 → 返回鍵，落在 ET03 我的課程（AC 1、2、3）", async () => {
    const user = userEvent.setup()
    const router = renderFlow(["/et/my-courses", "/et/courses/7/learn"])

    await user.click(await screen.findByRole("button", { name: "開始作答" }))
    await screen.findByText("採血前應先確認什麼？")
    expect(router.state.location.pathname).toBe("/et/attempts/800")

    await user.click(screen.getByRole("button", { name: "提交" }))
    await screen.findByText("測驗完成")
    expect(router.state.location.pathname).toBe("/et/attempts/800/result")

    // AC 3：結果頁上一頁不是作答中的頁面，而是（已帶 ?quiz= 的）學習頁
    await router.navigate(-1)
    await waitFor(() => expect(path(router)).toBe("/et/courses/7/learn?quiz=700"))
    await router.navigate(1)
    await screen.findByText("測驗完成")

    // AC 2：回課程落在帶 ?quiz= 的學習頁。
    // ⚠️ 等文案**穩定**再點：按鈕依「是否最新一次作答」顯示「回課程重新作答」或「返回課程」，
    // 歷次紀錄載入完成的那一刻會換字（fixture 另有較新的一次 → 穩定後為「返回課程」）。
    // 用 regex 兩者皆收的話，點擊可能落在換字的那一瞬間而落空（單跑全過、整目錄跑偶發紅）
    await user.click(await screen.findByRole("button", { name: "返回課程" }))
    await waitFor(() => expect(path(router)).toBe("/et/courses/7/learn?quiz=700"))
    expect(screen.getByTestId("learn-url")).toHaveTextContent("/et/courses/7/learn?quiz=700")

    // AC 1：學習頁按返回 → 我的課程
    await router.navigate(-1)
    expect(await screen.findByText("我的課程頁")).toBeInTheDocument()
  })

  it("從邀請信連結開學習頁（工作階段第一筆）→ 作答 → 回課程 → 學習頁返回，走 fallback 到 ET03（security review）", async () => {
    // 🔴 開始作答時學習頁網址被 replace 成帶 ?quiz=，key 不再是 "default"——若不帶「第一筆」
    // 標記，學習頁的返回鍵會以為有上一頁而 navigate(-1) 離站（新分頁沒反應、同分頁回到外站）
    const user = userEvent.setup()
    const router = renderFlow(["/et/courses/7/learn"])

    await user.click(await screen.findByRole("button", { name: "開始作答" }))
    await user.click(await screen.findByRole("button", { name: "提交" }))
    await user.click(await screen.findByRole("button", { name: "返回課程" }))
    await waitFor(() => expect(path(router)).toBe("/et/courses/7/learn?quiz=700"))

    await user.click(await screen.findByRole("button", { name: "學習頁返回" }))
    expect(await screen.findByText("我的課程頁")).toBeInTheDocument()
    // 以 replace 進 fallback：沒有多出一筆可以再退回學習頁
    expect(router.state.historyAction).toBe("REPLACE")
  })

  it("直接開作答頁網址（工作階段第一筆）→ 提交 → 返回課程 → 學習頁返回，全程不離站（code review MEDIUM）", async () => {
    // 作答頁以 replace 進結果頁，唯一的一筆被換成結果頁；state 帶「第一筆」標記，
    // 「返回課程」走 fallback（帶 ?quiz= 的學習頁）而非 navigate(-1) 離站
    const user = userEvent.setup()
    const router = renderFlow(["/et/attempts/800"])

    await user.click(await screen.findByRole("button", { name: "提交" }))
    await user.click(await screen.findByRole("button", { name: "返回課程" }))
    await waitFor(() => expect(path(router)).toBe("/et/courses/7/learn?quiz=700"))

    await user.click(await screen.findByRole("button", { name: "學習頁返回" }))
    expect(await screen.findByText("我的課程頁")).toBeInTheDocument()
  })

  it("從歷次作答紀錄進結果頁，回課程也落在帶 ?quiz= 的學習頁，再返回到 ET03（AC 5）", async () => {
    const user = userEvent.setup()
    // 學習頁網址**沒有** ?quiz=——學員是從側欄點進這個測驗的
    const router = renderFlow(["/et/my-courses", "/et/courses/7/learn"])

    await user.click(await screen.findByRole("button", { name: "回看第 1 次作答明細" }))
    await screen.findByText("測驗完成")

    await user.click(await screen.findByRole("button", { name: "返回課程" }))
    await waitFor(() => expect(path(router)).toBe("/et/courses/7/learn?quiz=700"))

    await router.navigate(-1)
    expect(await screen.findByText("我的課程頁")).toBeInTheDocument()
  })
})
