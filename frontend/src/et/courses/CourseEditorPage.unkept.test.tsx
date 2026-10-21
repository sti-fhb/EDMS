// #768（2026-10-20 使用者裁示）：進編輯頁丟棄未保留暫存的那支呼叫，只對課程擁有者打。
//
// 非擁有者（他人課程的檢視者、管理者）打下去必回 403，前端把任何失敗都講成「可能有上次
// 未更新的編輯殘留」——對一個根本不能按「更新」的人說這句是誤報。

import { screen, waitFor } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ courseId: "1" }),
    useLocation: () => ({ pathname: "/et/courses/1", state: null }),
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

function mockCourse(isOwner: boolean) {
  let discardCalls = 0
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status: "PUBLISHED",
        open_start_at: "2026-01-01T00:00:00Z",
        open_end_at: "2099-12-31T00:00:00Z",
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: isOwner,
        is_closed: false,
        has_pending_changes: false,
        audiences: [],
        chapters: [],
      }),
    ),
    http.delete("/api/et/courses/:courseId/content/stage/unkept", () => {
      discardCalls += 1
      // 比照後端：非擁有者一律 403
      return isOwner
        ? new HttpResponse(null, { status: 204 })
        : HttpResponse.json({ error_code: "ET_COURSE_002", error_message: "僅課程擁有者可操作" }, { status: 403 })
    }),
  )
  return () => discardCalls
}

describe("進編輯頁丟棄未保留暫存：只對擁有者呼叫（#768）", () => {
  it("非擁有者：不呼叫、不跳「可能有上次未更新的編輯殘留」", async () => {
    const calls = mockCourse(false)
    renderWithProviders(<EtCourseEditorPage />)

    // 正向錨點：課程已載入並預帶進表單。非擁有者的預帶要等丟棄「落定」，而它是由推導放行、
    // 不經呼叫——表單出現就代表 effect 已判過一次擁有權。⚠️ 之後再等一小段只是時間窗口，
    // 用來接住「判完才補打」這種延遲呼叫，不是嚴格證明（code review LOW）。
    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(calls()).toBe(0)
    expect(screen.queryByText(/可能有上次未更新的編輯殘留/)).not.toBeInTheDocument()
  })

  it("擁有者：照舊呼叫一次", async () => {
    const calls = mockCourse(true)
    renderWithProviders(<EtCourseEditorPage />)

    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
    await waitFor(() => expect(calls()).toBe(1))
  })
})


describe("丟棄落定前不預帶表單（#720 的保護，#768 改了呼叫時機後補守門）", () => {
  it("丟棄回應前表單是空的；回應後才預帶", async () => {
    // 丟棄現在要等課程載入、知道擁有權才打（原本與 GET 並行）。保護的是同一件事：GET 回的是
    // 殘留值，丟棄完成前就預帶的話，殘留會被鎖進表單、按「更新」又推給學員。
    let release: () => void = () => {}
    let requested = false
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    mockCourse(true)
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage/unkept", async () => {
        requested = true
        await gate
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderWithProviders(<EtCourseEditorPage />)

    // 正向錨點：丟棄已送到伺服器（課程也已載入，否則不會打）——此刻仍不得預帶
    await waitFor(() => expect(requested).toBe(true))
    expect(screen.queryByDisplayValue("採血作業訓練")).not.toBeInTheDocument()
    release()
    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
  })
})
