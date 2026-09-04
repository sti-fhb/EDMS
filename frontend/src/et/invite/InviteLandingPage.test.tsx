import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { EtInviteLandingPage } from "./InviteLandingPage"

const mockNavigate = vi.fn()
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom")
  return { ...actual, useNavigate: () => mockNavigate }
})

/** 以指定網址渲染落點頁（token 由 query string 帶入）。 */
function renderAt(url: string) {
  mockNavigate.mockClear()
  return renderWithProviders(<EtInviteLandingPage />, undefined, [url])
}

describe("EtInviteLandingPage", () => {
  it("token 有效時導向該課程的學習頁", async () => {
    renderAt("/et/invite?token=good-token")

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/et/courses/7/learn", { replace: true })
    })
  })

  it("已加入者同樣導向學習頁，不顯示錯誤", async () => {
    // AC 8：「你已經加入過了」對學員不是有用的資訊，直接帶他進課程
    server.use(
      http.post("/api/et/invitations/accept", () =>
        HttpResponse.json({ course_id: 12, course_name: "感染管制年度訓練", already_joined: true }),
      ),
    )
    renderAt("/et/invite?token=used-by-me")

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/et/courses/12/learn", { replace: true })
    })
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("連結已被使用過時顯示失效訊息與返回入口", async () => {
    server.use(
      http.post("/api/et/invitations/accept", () =>
        HttpResponse.json(
          { error_code: "ET_INVITE_001", error_message: "邀請連結無效或已失效" },
          { status: 404 },
        ),
      ),
    )
    renderAt("/et/invite?token=consumed")

    expect(await screen.findByText("邀請連結無效或已失效")).toBeInTheDocument()
    expect(screen.getByText(/邀請連結為一次性/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "前往我的課程" })).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it("課程關閉期間顯示關閉中訊息", async () => {
    server.use(
      http.post("/api/et/invitations/accept", () =>
        HttpResponse.json({ error_code: "ET_INVITE_002", error_message: "此課程目前關閉中" }, { status: 409 }),
      ),
    )
    renderAt("/et/invite?token=closed-course")

    expect(await screen.findByText("此課程目前關閉中")).toBeInTheDocument()
  })

  it("網址缺 token 時直接顯示失效，不打 API", async () => {
    let called = false
    server.use(
      http.post("/api/et/invitations/accept", () => {
        called = true
        return HttpResponse.json({ course_id: 1, course_name: "x", already_joined: false })
      }),
    )
    renderAt("/et/invite")

    expect(await screen.findByText("邀請連結無效或已失效")).toBeInTheDocument()
    expect(called).toBe(false)
  })
})
