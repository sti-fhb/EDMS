import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { RequireDmReviewer, RequireModuleAdmin } from "./RequireAccess"
import { renderWithProviders } from "../test/renderWithProviders"
import { server } from "../test/server"

/**
 * 路由層權限守衛（#250）：直接輸入網址時要看到明確的無權限畫面。
 *
 * 沒有守衛時的實際症狀——非管理者開 /dp/users 停在載入中（後端 403 但頁面無錯誤處理）、
 * 開 /dm/review 渲染出簽核畫面空殼，兩者都像壞掉。
 */

const CHILD = <div>受保護內容</div>

function summaryHandler(etAdmin: boolean, dmAdmin: boolean, dmHasRole = true) {
  return http.get("/api/dp/user/module-summary", () =>
    HttpResponse.json({
      et: { has_role: true, is_admin: etAdmin },
      dm: { has_role: dmHasRole, is_admin: dmAdmin },
    }),
  )
}

describe("RequireModuleAdmin", () => {
  it("非 ET 且非 DM 管理者 → 顯示 403 無權限畫面，不渲染子頁", async () => {
    server.use(summaryHandler(false, false))
    renderWithProviders(<RequireModuleAdmin>{CHILD}</RequireModuleAdmin>)
    expect(await screen.findByText("無存取權限（HTTP 403）")).toBeInTheDocument()
    expect(screen.queryByText("受保護內容")).not.toBeInTheDocument()
  })

  it("具任一模組管理者 → 正常渲染子頁", async () => {
    server.use(summaryHandler(false, true))
    renderWithProviders(<RequireModuleAdmin>{CHILD}</RequireModuleAdmin>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
    expect(screen.queryByText("無存取權限（HTTP 403）")).not.toBeInTheDocument()
  })

  it("summary 未載入前不渲染子頁（fail-closed，避免先閃內容再收回）", () => {
    server.use(summaryHandler(true, true))
    renderWithProviders(<RequireModuleAdmin>{CHILD}</RequireModuleAdmin>)
    expect(screen.queryByText("受保護內容")).not.toBeInTheDocument()
  })
})

describe("RequireDmReviewer", () => {
  it("具 DM 角色但非審核者 → 403 畫面（僅 DM_ADMIN 者亦然）", async () => {
    server.use(summaryHandler(false, true), http.get("/api/dm/reviewer-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<RequireDmReviewer>{CHILD}</RequireDmReviewer>)
    expect(await screen.findByText("無存取權限（HTTP 403）")).toBeInTheDocument()
    expect(screen.queryByText("受保護內容")).not.toBeInTheDocument()
  })

  it("具審核者 → 正常渲染簽核頁", async () => {
    server.use(summaryHandler(false, false), http.get("/api/dm/reviewer-access", () => HttpResponse.json({ can_access: true })))
    renderWithProviders(<RequireDmReviewer>{CHILD}</RequireDmReviewer>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })

  it("完全無 DM 角色 → 403 畫面，且不觸發 reviewer-access 查詢（避免 403 噪音）", async () => {
    let called = 0
    server.use(
      summaryHandler(false, false, false),
      http.get("/api/dm/reviewer-access", () => {
        called += 1
        return HttpResponse.json({ can_access: false })
      }),
    )
    renderWithProviders(<RequireDmReviewer>{CHILD}</RequireDmReviewer>)
    expect(await screen.findByText("無存取權限（HTTP 403）")).toBeInTheDocument()
    await waitFor(() => expect(called).toBe(0))
  })
})
