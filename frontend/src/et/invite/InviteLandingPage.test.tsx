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

  it("邀請已被教師撤回時顯示專用訊息（ET-MSG-ET03-104）", async () => {
    // ET-12 / #342。後端於 2026-09-16 起把「已撤回」自 ET_INVITE_001 分流為
    // ET_INVITE_006（410），本頁**不需要特別處理**——它直接渲染後端的 error_message。
    //
    // 本測試釘住的正是這個「不需要處理」：若日後有人把錯誤呈現改成固定文案，或依
    // error_code 寫死對照表而漏了 006，受邀者會看回「連結無效」——那與 FR-ET-US12-05
    // 要求的「此邀請已撤回」不符，而且他會以為是信壞了、跑去找教師。
    server.use(
      http.post("/api/et/invitations/accept", () =>
        HttpResponse.json({ error_code: "ET_INVITE_006", error_message: "此邀請已撤回" }, { status: 410 }),
      ),
    )
    renderAt("/et/invite?token=revoked-one")

    expect(await screen.findByText("此邀請已撤回")).toBeInTheDocument()
    expect(screen.queryByText("邀請連結無效或已失效")).not.toBeInTheDocument()
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
