import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import {
  RequireDmAdmin,
  RequireDmEditor,
  RequireDmPersonal,
  RequireDmReviewer,
  RequireEtCourseCreator,
  RequireEtCourseManager,
  RequireModule,
  RequireModuleAdmin,
} from "./RequireAccess"
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
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
    // 所有守衛共用同一元件、同一段文字（各 describe 皆斷言此字串，即為一致性保證）
    expect(screen.getByText("如需使用此功能，請洽模組管理者為您指派對應角色。")).toBeInTheDocument()
    expect(screen.queryByText("受保護內容")).not.toBeInTheDocument()
  })

  it("具任一模組管理者 → 正常渲染子頁", async () => {
    server.use(summaryHandler(false, true))
    renderWithProviders(<RequireModuleAdmin>{CHILD}</RequireModuleAdmin>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
    expect(screen.queryByText("無權限存取此功能")).not.toBeInTheDocument()
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
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
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
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
    await waitFor(() => expect(called).toBe(0))
  })
})

describe("RequireModule（模組群組門檻）", () => {
  it("無該模組任一角色 → 無權限畫面", async () => {
    server.use(summaryHandler(false, false, false))
    renderWithProviders(<RequireModule module="DM">{CHILD}</RequireModule>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
  })

  it("具該模組角色 → 渲染子頁", async () => {
    server.use(summaryHandler(false, false, true))
    renderWithProviders(<RequireModule module="DM">{CHILD}</RequireModule>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })
})

describe("RequireDmAdmin（已廢止 / 變更歷程 / KPI）", () => {
  it("非 DM 管理者 → 無權限畫面", async () => {
    server.use(summaryHandler(false, false), http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<RequireDmAdmin>{CHILD}</RequireDmAdmin>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
  })

  it("DM 管理者 → 渲染子頁", async () => {
    server.use(summaryHandler(false, true), http.get("/api/dm/admin-access", () => HttpResponse.json({ can_access: true })))
    renderWithProviders(<RequireDmAdmin>{CHILD}</RequireDmAdmin>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })
})

describe("RequireDmPersonal（個人專區）", () => {
  it("非編輯者 / 審核者 → 無權限畫面", async () => {
    server.use(summaryHandler(false, false), http.get("/api/dm/personal/access", () => HttpResponse.json({ can_access: false })))
    renderWithProviders(<RequireDmPersonal>{CHILD}</RequireDmPersonal>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
  })

  it("具編輯者或審核者 → 渲染子頁", async () => {
    server.use(summaryHandler(false, false), http.get("/api/dm/personal/access", () => HttpResponse.json({ can_access: true })))
    renderWithProviders(<RequireDmPersonal>{CHILD}</RequireDmPersonal>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })
})

/** ET module-summary handler（`summaryHandler` 之 et.has_role 恆為 true，此處可控）。 */
function etSummaryHandler(etHasRole: boolean) {
  return http.get("/api/dp/user/module-summary", () =>
    HttpResponse.json({
      et: { has_role: etHasRole, is_admin: false },
      dm: { has_role: false, is_admin: false },
    }),
  )
}

// #306：編輯器路由原本只有群組層 RequireModule，直接輸入網址會渲染出完整編輯器空殼。

describe("RequireDmEditor", () => {
  it("具 DM 角色但非編輯者（can_create=false）→ 無權限畫面，不渲染編輯器", async () => {
    server.use(
      summaryHandler(false, false),
      http.get("/api/dm/library/capabilities", () => HttpResponse.json({ can_create: false })),
    )
    renderWithProviders(<RequireDmEditor>{CHILD}</RequireDmEditor>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
    expect(screen.queryByText("受保護內容")).not.toBeInTheDocument()
  })

  it("具編輯者 → 正常渲染子頁", async () => {
    server.use(summaryHandler(false, false)) // 預設 handler：can_create=true
    renderWithProviders(<RequireDmEditor>{CHILD}</RequireDmEditor>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })

  it("無任何 DM 角色 → 無權限畫面，且不打 capabilities（避免非 DM 使用者觸發 403）", async () => {
    let called = 0
    server.use(
      summaryHandler(false, false, false),
      http.get("/api/dm/library/capabilities", () => {
        called += 1
        return HttpResponse.json({ can_create: true })
      }),
    )
    renderWithProviders(<RequireDmEditor>{CHILD}</RequireDmEditor>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
    expect(called).toBe(0)
  })
})

describe("RequireEtCourseCreator", () => {
  it("非教師（can_create_course=false）→ 無權限畫面", async () => {
    server.use(
      etSummaryHandler(true),
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: true, can_learn: true }),
      ),
    )
    renderWithProviders(<RequireEtCourseCreator>{CHILD}</RequireEtCourseCreator>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
  })

  it("具教師 → 正常渲染子頁", async () => {
    server.use(etSummaryHandler(true)) // 預設 handler：can_create_course=true
    renderWithProviders(<RequireEtCourseCreator>{CHILD}</RequireEtCourseCreator>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })
})

describe("RequireEtCourseManager", () => {
  it("純管理者（can_create_course=false 但 can_manage_courses=true）→ 可進課程編輯頁", async () => {
    // 用 can_create_course 包這條路由會誤擋純管理者——schema 明載兩者角色集不同
    server.use(
      etSummaryHandler(true),
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: true, can_learn: true }),
      ),
    )
    renderWithProviders(<RequireEtCourseManager>{CHILD}</RequireEtCourseManager>)
    expect(await screen.findByText("受保護內容")).toBeInTheDocument()
  })

  it("純學員（兩者皆 false）→ 無權限畫面", async () => {
    server.use(
      etSummaryHandler(true),
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: false, can_learn: true }),
      ),
    )
    renderWithProviders(<RequireEtCourseManager>{CHILD}</RequireEtCourseManager>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
  })

  it("無任何 ET 角色 → 無權限畫面，且不打 capabilities", async () => {
    let called = 0
    server.use(
      etSummaryHandler(false),
      http.get("/api/et/courses/capabilities", () => {
        called += 1
        return HttpResponse.json({ can_create_course: true, can_manage_courses: true, can_learn: true })
      }),
    )
    renderWithProviders(<RequireEtCourseManager>{CHILD}</RequireEtCourseManager>)
    expect(await screen.findByText("無權限存取此功能")).toBeInTheDocument()
    expect(called).toBe(0)
  })
})
