// #768 第 11 項：「更新並重開課」撞上問卷凍結（422 ET_SURVEY_003）時，比照「更新」開出帶
// 出口的視窗（#712），而不是一則短暫訊息——教師改不回去，整門課就重開不了。
//
// ⚠️ 另開一檔：`CourseEditorPage.reopen.test.tsx` 已超過 800 行（#688 的教訓）。

import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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

describe("更新並重開課撞上問卷凍結（#768 第 11 項）", () => {
  it("開出帶「放棄問卷的編輯」的視窗，說明重按「更新並重開課」", async () => {
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "採血作業訓練",
          description: null,
          status: "CLOSED",
          open_start_at: "2026-01-01T00:00:00Z",
          open_end_at: "2099-12-31T00:00:00Z",
          require_approval: false,
          version: 3,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          is_closed: true,
          has_pending_changes: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
        }),
      ),
      http.post("/api/et/courses/:courseId/reopen", () =>
        HttpResponse.json(
          { error_code: "ET_SURVEY_003", error_message: "已有學員填答，題目與選項不可修改" },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtCourseEditorPage />)
    await user.click(await screen.findByRole("button", { name: "更新並重開課" }))

    expect(await screen.findByRole("button", { name: "放棄問卷的編輯" })).toBeInTheDocument()
    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveTextContent("再按一次「更新並重開課」")
    expect(dialog).not.toHaveTextContent("再按一次「更新」即可")

    // 放棄之後的訊息要講下一步——重開課情境是「更新並重開課」，不是「更新」
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage/survey", () => new HttpResponse(null, { status: 204 })),
    )
    await user.click(screen.getByRole("button", { name: "放棄問卷的編輯" }))
    expect(await screen.findByText(/請再按一次「更新並重開課」/)).toBeInTheDocument()
  }, 15000)
})
