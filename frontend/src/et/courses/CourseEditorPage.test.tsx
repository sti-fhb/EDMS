import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// useParams 可變（切換新增 / 編輯模式）；比照 DM `DmEditorPage.test.tsx`
// ——`renderWithProviders` 內建之 MemoryRouter 無法指定 initialEntries。
const { navigateSpy, paramsRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy, useParams: () => paramsRef.current }
})

/** 編輯模式：帶 courseId 路由參數。 */
function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

/** 新增模式：無路由參數。**不可寫成 `renderNewEditor()`**——傳 undefined 會
 *  觸發預設參數而變成編輯模式，是難以察覺的假通過。 */
function renderNewEditor() {
  paramsRef.current = {}
  return renderWithProviders(<EtCourseEditorPage />)
}

beforeEach(() => {
  navigateSpy.mockClear()
})

describe("ET02 課程編輯頁", () => {
  it("編輯模式載入既有課程資料與章節", async () => {
    renderEditor()
    expect(await screen.findByDisplayValue("採血作業訓練")).toBeInTheDocument()
    expect(await screen.findByDisplayValue("第一章")).toBeInTheDocument()
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()
  })

  it("新增模式為空白表單，且章節區提示須先儲存草稿", async () => {
    renderNewEditor()
    expect(await screen.findByRole("heading", { name: "新增課程" })).toBeInTheDocument()
    expect(screen.getByText("請先儲存草稿後再新增章節")).toBeInTheDocument()
  })

  it("課程名稱留空時擋下送出並顯示錯誤", async () => {
    const user = userEvent.setup()
    renderNewEditor()
    await user.click(await screen.findByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("請輸入課程名稱")).toBeInTheDocument()
  })

  it("課程描述超過 500 字時擋下送出", async () => {
    const user = userEvent.setup()
    renderEditor()
    const description = await screen.findByLabelText(/課程描述/)
    await user.clear(description)
    await user.paste("字".repeat(501))
    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("課程描述不可超過 500 字")).toBeInTheDocument()
  })

  it("非擁有者為檢視模式：顯示提示、無儲存按鈕", async () => {
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "他人的課",
          description: null,
          status: "DRAFT",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 0,
          owner_id: "OTHER",
          owner_name: "林助教",
          is_owner: false,
          tag_ids: [],
          chapters: [{ chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0 }],
        }),
      ),
    )
    renderEditor()
    expect(await screen.findByText(/檢視模式/)).toBeInTheDocument()
    expect(screen.getByText("林助教")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存草稿" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增章節" })).not.toBeInTheDocument()
  })

  it("版本衝突時以對話框呈現而非 snackbar", async () => {
    const user = userEvent.setup()
    server.use(
      http.put("/api/et/courses/:courseId", () =>
        HttpResponse.json(
          { error_code: "ET_LOCK_001", error_message: "資料已被其他使用者修改，請重新載入後再試" },
          { status: 409 },
        ),
      ),
    )
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "儲存草稿" }))
    expect(await screen.findByText("內容已被其他裝置變更，請重新整理後再儲存。")).toBeInTheDocument()
  })

  it("已發布課程之標籤不可移除（chip 無刪除鈕）", async () => {
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "已發布課",
          description: null,
          status: "PUBLISHED",
          open_start_at: null,
          open_end_at: null,
          require_approval: false,
          version: 3,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          tag_ids: [2],
          chapters: [],
        }),
      ),
    )
    renderEditor()
    expect(await screen.findByText("已發布課程可新增標籤、不可移除既有標籤")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText("護理師")).toBeInTheDocument())
    // MUI Chip 的刪除鈕 aria-label 預設為 "delete"；不可移除時不應出現
    expect(screen.queryByTestId("CancelIcon")).not.toBeInTheDocument()
  })

  it("新增章節對話框支援「儲存並繼續新增」", async () => {
    const user = userEvent.setup()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "新增章節" }))

    const input = await screen.findByLabelText("章節名稱")
    await user.type(input, "第三章")
    await user.click(screen.getByRole("button", { name: "儲存並繼續新增" }))

    // 對話框留著、欄位重設——教師可連續新增多個章節
    await waitFor(() => expect(screen.getByLabelText("章節名稱")).toHaveValue(""))
    expect(screen.getByRole("button", { name: "儲存並繼續新增" })).toBeInTheDocument()
  })

  it("章節名稱留空時於對話框內顯示錯誤且不關閉", async () => {
    const user = userEvent.setup()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.click(await screen.findByRole("button", { name: "儲存" }))
    expect(await screen.findByText("請輸入章節名稱")).toBeInTheDocument()
  })
})
