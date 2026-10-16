import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/**
 * ET05「更新」：把暫存的內容編輯整批生效給學員（#631）。
 *
 * ## 為何另開一個檔，而不是加進 `CourseEditorPage.test.tsx`
 *
 * 那個檔已經是全專案最大的測試檔（#682：86 條 `it()`，整組跑時一檔獨佔 210~310 秒，
 * 檔內又用 vitest 預設的 5s timeout，於是自己把自己擠到逾時——**乾淨機器上照樣會紅**，
 * 不是負載造成的）。往裡面再塞 9 條只會讓它更糟，而且本組的結論會被那個雜訊蓋掉。
 * vitest 以**檔**為平行單位，分檔即分開排程。
 *
 * ## 本組守的是「教師知不知道學員看到了什麼」
 *
 * #631 把「編輯」與「學員看到」拆成兩個時點，而已發布課程的內容讀取回的是**暫存版**
 * ——教師在畫面上看得到自己剛加的章節，與「學員也看得到」在視覺上毫無分別。整個功能
 * 的新風險集中在這一點，所以提示文字與按鈕狀態都要有測試釘住。
 */

const { navigateSpy, paramsRef, locationRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: { courseId: "1" } as Record<string, string | undefined> },
  locationRef: { current: { pathname: "/et/courses/1", state: null } as { pathname: string; state: unknown } },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    // 離開攔截需要 data router，`renderWithProviders` 內建的是 MemoryRouter——真的
    // `useBlocker` 在此會拋錯。以「永不攔截」取代，站內離開的攔截屬 e2e 行為
    //（比照 `DmEditorPage.test.tsx` 與 `QuizAnswerPage.test.tsx`）。
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

/**
 * 以指定狀態、擁有權與暫存狀態覆蓋課程詳細。
 *
 * `pending` 對應後端的 `has_pending_changes`：有尚未按下「更新」的內容編輯。
 */
function useCourse(
  status: string,
  { isOwner = true, pending = false }: { isOwner?: boolean; pending?: boolean } = {},
) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status,
        open_start_at: "2026-09-01T00:00:00Z",
        open_end_at: "2027-09-30T00:00:00Z",
        require_approval: false,
        version: 5,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: isOwner,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [],
        invitation_code: isOwner ? "01234567" : null,
        has_pending_changes: pending,
      }),
    ),
  )
}

function renderEditor() {
  paramsRef.current = { courseId: "1" }
  return renderWithProviders(<EtCourseEditorPage />)
}

describe("ET05 更新（#631）", () => {
  it.each([["PUBLISHED"], ["CLOSED"]])(
    "%s 課程顯示「更新」鈕（關閉期間的編輯同樣要按更新才生效）",
    async (status) => {
      useCourse(status, { pending: true })
      renderEditor()
      expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled()
    },
  )

  it("草稿不顯示「更新」鈕——草稿的編輯直接寫活表，沒有要更新的東西", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")

    expect(screen.queryByRole("button", { name: "更新" })).not.toBeInTheDocument()
    // 正向錨點：草稿有自己那顆（少了它，上一條在「整列按鈕都沒畫出來」時也會通過）
    expect(screen.getByRole("button", { name: "儲存並發布" })).toBeInTheDocument()
  })

  it("沒有暫存變更時「更新」鈕停用，且提示不說有變更", async () => {
    useCourse("PUBLISHED", { pending: false })
    renderEditor()

    expect(await screen.findByRole("button", { name: "更新" })).toBeDisabled()
    expect(screen.getByText(/按「更新」才整批對學員生效/)).toBeInTheDocument()
    expect(screen.queryByText(/有尚未更新的變更/)).not.toBeInTheDocument()
  })

  it("🔴 有暫存變更時提示明寫「只有你看得到」——本功能的新風險就在這句話上", async () => {
    // 少了它，教師編完直接離開會以為學員已經看到了，而下一次知道真相的時機是學員反映
    // 「課程沒有更新」。反向斷言（上一條的 queryByText）與這條用同一種查法。
    useCourse("PUBLISHED", { pending: true })
    renderEditor()

    expect(await screen.findByText(/有尚未更新的變更/)).toBeInTheDocument()
    expect(screen.getByText(/目前只有你看得到/)).toBeInTheDocument()
  })

  it("按下「更新」先二次確認，確認後才送出；確認內容說明刪除會連帶移除學員進度", async () => {
    // 這一下會同時影響所有在籍學員，且被刪掉的章節 / 項目會連帶移除其進度與作答。
    const user = userEvent.setup()
    let applies = 0
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () => {
        applies += 1
        return HttpResponse.json({ course_id: 1, applied_count: 3 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))

    expect(await screen.findByText(/學習進度與測驗作答會一併移除/)).toBeInTheDocument()
    expect(applies).toBe(0) // 確認前不送出

    await user.click(screen.getByRole("button", { name: "確認更新" }))

    await waitFor(() => expect(applies).toBe(1))
    expect(await screen.findByText("課程內容已更新，學員已可看到")).toBeInTheDocument()
  })

  it("暫存區是空的（applied_count 0）時不報「已更新」——那是一件沒發生的事", async () => {
    // 按鈕平時由 `has_pending_changes` 擋著按不到，但那個旗標會過期：另一個分頁剛按過
    // 更新時就會走到這條路。後端此時是安全的 no-op，訊息也要照實講。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json({ course_id: 1, applied_count: 0 }),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    expect(await screen.findByText("目前沒有需要更新的變更")).toBeInTheDocument()
    expect(screen.queryByText("課程內容已更新，學員已可看到")).not.toBeInTheDocument()
  })

  it("檢核未通過（422 ET_PUBLISH_001）時列出缺漏，並說明編輯仍保留在暫存區", async () => {
    // 🔴 「編輯仍保留」是這個視窗與發布那個最大的差別：教師按下更新被擋，第一個念頭是
    // 「我剛才改的東西還在嗎」。不講，他會從頭再改一次。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json(
          {
            error_code: "ET_PUBLISH_001",
            error_message: "更新條件未滿足",
            blockers: [{ code: "CHAPTER_EMPTY", message: "章節至少須有 1 份教材或測驗", target_id: 11 }],
          },
          { status: 422 },
        ),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    const dialog = await screen.findByRole("dialog", { name: "更新未生效" })
    expect(await within(dialog).findByText(/章節至少須有 1 份教材或測驗/)).toBeInTheDocument()
    expect(within(dialog).getByText(/編輯仍保留在暫存區/)).toBeInTheDocument()
    expect(screen.queryByText("課程內容已更新，學員已可看到")).not.toBeInTheDocument()
  })

  it("🔴 問卷凍結（422 ET_SURVEY_003）走訊息，不被當成缺漏吞掉", async () => {
    // 缺漏清單裝不下這一條（它不是「少了什麼」而是「不准改」）。若比照 ET_PUBLISH_001
    // 一起吞進缺漏處理，畫面會是「按了更新、什麼都沒發生」——最難察覺的一種失敗。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json(
          { error_code: "ET_SURVEY_003", error_message: "已有學員填答，題目與選項不可修改" },
          { status: 422 },
        ),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    expect(await screen.findByText("已有學員填答，題目與選項不可修改")).toBeInTheDocument()
    // 用與上一條**同一種查法**（上一條是它的正向錨點，證明這個名字查得到東西）
    expect(screen.queryByRole("dialog", { name: "更新未生效" })).not.toBeInTheDocument()
  })

  it("非擁有者（檢視模式）看不到「更新」鈕", async () => {
    // ⚠️ 刻意餵 `pending: true`（後端對他人恆回 false）：要驗的是**前端自己那道
    // `readOnly` 閘**，不是「旗標剛好是 false 所以按鈕沒亮」。餵 false 的話，把
    // `readOnly` 拿掉這條照樣通過。
    useCourse("PUBLISHED", { isOwner: false, pending: true })
    renderEditor()
    await screen.findByText(/檢視模式/)

    expect(screen.queryByRole("button", { name: "更新" })).not.toBeInTheDocument()
  })
})
