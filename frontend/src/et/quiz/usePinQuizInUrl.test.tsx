/**
 * `usePinQuizInUrl`（#549）——以真 router 驗「只動 `?quiz=`、其餘原樣、不新增歷程」。
 *
 * 呼叫端的單元測試都 mock 了 `useNavigate`，看不到網址實際變成什麼（code review MEDIUM）。
 */
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { RouterProvider, createMemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { usePinQuizInUrl } from "./usePinQuizInUrl"

function Pinner() {
  const pin = usePinQuizInUrl(700)
  return (
    <button type="button" onClick={() => void pin()}>
      釘住
    </button>
  )
}

function setup(entry: string) {
  const router = createMemoryRouter([{ path: "/et/courses/:courseId/learn", element: <Pinner /> }], {
    initialEntries: ["/et/my-courses", entry],
    initialIndex: 1,
  })
  render(<RouterProvider router={router} />)
  return router
}

describe("usePinQuizInUrl", () => {
  it("加上 ?quiz= 時保留其他 query 與 hash，且以 replace 進行（不新增歷程）", async () => {
    const user = userEvent.setup()
    const router = setup("/et/courses/7/learn?foo=1#top")

    await user.click(screen.getByRole("button", { name: "釘住" }))

    const params = new URLSearchParams(router.state.location.search)
    expect(params.get("quiz")).toBe("700")
    expect(params.get("foo")).toBe("1")
    expect(router.state.location.hash).toBe("#top")
    expect(router.state.historyAction).toBe("REPLACE")
    // 歷程沒有變長：退一格就是我的課程
    await router.navigate(-1)
    expect(router.state.location.pathname).toBe("/et/my-courses")
  })

  it("已帶同一個 ?quiz= 時不導向（這一筆原封不動）", async () => {
    const user = userEvent.setup()
    const router = setup("/et/courses/7/learn?quiz=700")
    const keyBefore = router.state.location.key

    await user.click(screen.getByRole("button", { name: "釘住" }))

    // 正向錨點：網址確實是帶 quiz=700 的那一筆——下面「key 沒變」才代表「沒有導向」而非「導到別處」
    expect(router.state.location.search).toBe("?quiz=700")
    expect(router.state.location.key).toBe(keyBefore)
  })

  it("帶的是另一個測驗時改成本測驗", async () => {
    const user = userEvent.setup()
    const router = setup("/et/courses/7/learn?quiz=699")

    await user.click(screen.getByRole("button", { name: "釘住" }))

    expect(new URLSearchParams(router.state.location.search).get("quiz")).toBe("700")
  })
})
