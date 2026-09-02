import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { HttpResponse, http } from "msw"
import type { ReactNode } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { EtHomeRedirect } from "./EtHomeRedirect"
import { server } from "../test/server"

/** 需要真的看見「轉址到哪裡」，故不能用 renderWithProviders（它固定 MemoryRouter 無子路由）。 */
function renderAt(capabilities?: { can_create_course: boolean }) {
  if (capabilities) {
    server.use(http.get("/api/et/courses/capabilities", () => HttpResponse.json(capabilities)))
  }
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }

  return render(
    <MemoryRouter initialEntries={["/et"]}>
      <Routes>
        <Route path="/et" element={<EtHomeRedirect />} />
        <Route path="/et/courses" element={<div>課程列表</div>} />
        <Route path="/et/my-courses" element={<div>我的課程</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper: Wrapper },
  )
}

describe("ET 首頁角色導向（AC 1）", () => {
  it("純學員導向 ET04 我的課程", async () => {
    renderAt({ can_create_course: false })

    expect(await screen.findByText("我的課程")).toBeInTheDocument()
  })

  it("具建課能力者導向課程列表", async () => {
    renderAt({ can_create_course: true })

    // 教師同時也是學員（學員角色人人有）；一律送到 ET04 會讓他每次進 ET 都要多點一次。
    expect(await screen.findByText("課程列表")).toBeInTheDocument()
  })

  it("能力查詢失敗時導向 ET04（每個 ET 使用者都進得去）", async () => {
    server.use(http.get("/api/et/courses/capabilities", () => new HttpResponse(null, { status: 500 })))
    renderAt()

    // 課程列表對純學員是死路，失敗時往那裡送更糟。
    expect(await screen.findByText("我的課程")).toBeInTheDocument()
  })
})
