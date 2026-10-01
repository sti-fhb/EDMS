import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { useGoBack } from "./useGoBack"

function PageA() {
  const navigate = useNavigate()
  return (
    <div>
      <p>頁面 A</p>
      <button onClick={() => navigate("/b")}>去 B</button>
    </div>
  )
}

function PageB() {
  const goBack = useGoBack("/fallback")
  return (
    <div>
      <p>頁面 B</p>
      <button onClick={goBack}>返回</button>
    </div>
  )
}

function Harness({ initial }: { initial: string }) {
  return (
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/a" element={<PageA />} />
        <Route path="/b" element={<PageB />} />
        <Route path="/fallback" element={<p>備援頁</p>} />
      </Routes>
    </MemoryRouter>
  )
}

describe("useGoBack", () => {
  it("歷程中有上一頁時退回該頁，不走 fallback", async () => {
    const user = userEvent.setup()
    render(<Harness initial="/a" />)

    await user.click(screen.getByRole("button", { name: "去 B" }))
    expect(screen.getByText("頁面 B")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "返回" }))
    expect(screen.getByText("頁面 A")).toBeInTheDocument()
    // 配對斷言：少了這條，實作改成無條件 navigate(fallback) 也會通過上一條嗎？
    // 不會（會停在備援頁），但補上它才能讓「走錯分支」的失敗訊息直接指出原因。
    expect(screen.queryByText("備援頁")).not.toBeInTheDocument()
  })

  it("直接進入（歷程第一筆，無上一頁）時導向 fallback，不退出本站", async () => {
    const user = userEvent.setup()
    render(<Harness initial="/b" />)

    await user.click(screen.getByRole("button", { name: "返回" }))
    expect(screen.getByText("備援頁")).toBeInTheDocument()
    expect(screen.queryByText("頁面 B")).not.toBeInTheDocument()
  })
})
