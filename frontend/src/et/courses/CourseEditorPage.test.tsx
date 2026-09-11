import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { coursesApi } from "./coursesService"
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

  it("新增模式即可直接新增章節（暫存於畫面，儲存時一次建立）", async () => {
    const user = userEvent.setup()
    renderNewEditor()
    expect(await screen.findByRole("heading", { name: "新增課程" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 尚未儲存課程，章節僅存在於畫面
    expect(await screen.findByDisplayValue("第一章")).toBeInTheDocument()
  })

  it("暫存章節的識別不隨位置改變——刪除第一章後剩下的仍顯示自己的名稱", async () => {
    // 迴歸測試：暫存章節的 id 原本是 `-(index + 1)`，由位置推導。
    // `ChapterRow` 以 chapter_id 當 React key 且內部以 state 保存名稱草稿，
    // 位置一變 key 就對到別人，React 重用同一個元件實例、草稿不更新——
    // 拖拉後畫面「看起來沒動」、刪除後剩下的會顯示被刪者的名稱。
    const user = userEvent.setup()
    renderNewEditor()
    await screen.findByRole("heading", { name: "新增課程" })

    for (const name of ["第一章", "第二章"]) {
      await user.click(screen.getByRole("button", { name: "新增章節" }))
      const input = await screen.findByLabelText("章節名稱")
      await user.click(input)
      await user.paste(name) // 貼上為單次事件，比逐字 type 快很多
      await user.click(screen.getByRole("button", { name: "儲存" }))
      await waitFor(() => expect(screen.queryByLabelText("章節名稱")).not.toBeInTheDocument())
    }
    expect(screen.getByDisplayValue("第一章")).toBeInTheDocument()
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()

    // 暫存章節無學員紀錄可連帶處理，故刪除不跳 confirm
    await user.click(screen.getByRole("button", { name: "刪除章節 第一章" }))

    await waitFor(() => expect(screen.queryByDisplayValue("第一章")).not.toBeInTheDocument())
    expect(screen.getByDisplayValue("第二章")).toBeInTheDocument()
    // 本條互動數明顯多於其他測試（兩輪對話框開關 + 刪除），全套件滿載時預設 5s 不夠；
    // 拉長 timeout 而非削弱斷言——它驗的是拖拉 / 刪除失效的根因，不宜簡化。
  }, 15000)

  it("新增模式儲存時一次送出課程與暫存章節，並導回列表", async () => {
    const user = userEvent.setup()
    // 用可變容器而非 `let`：`let` 只在 closure 內賦值時，TS 的控制流分析會把
    // closure 外的讀取收斂成 `null`（屬性存取即報 never）。物件屬性不受此收斂影響。
    const captured: { body?: { chapters: string[]; open_start_at: string | null; open_end_at: string | null } } = {}
    server.use(
      http.post("/api/et/courses", async ({ request }) => {
        captured.body = (await request.json()) as NonNullable<typeof captured.body>
        return HttpResponse.json({ course_id: 99, version: 0 }, { status: 201 })
      }),
    )
    renderNewEditor()
    await user.type(await screen.findByRole("textbox", { name: "課程名稱" }), "新課程")
    await user.click(screen.getByRole("button", { name: "新增章節" }))
    await user.type(await screen.findByLabelText("章節名稱"), "第一章")
    await user.click(screen.getByRole("button", { name: "儲存" }))
    // MUI Dialog 關閉有退場動畫，期間仍在 DOM 且對背景設 aria-hidden；
    // 用 findBy* 等它真的消失，否則背景按鈕查不到（同步 getByRole 會失敗）。
    await user.click(await screen.findByRole("button", { name: "儲存草稿" }))

    await waitFor(() => expect(captured.body?.chapters).toEqual(["第一章"]))
    // 起訖時間於草稿允許留空（FR-ET-US3-01）——未填即送 null，不送空字串
    expect(captured.body?.open_start_at).toBeNull()
    expect(captured.body?.open_end_at).toBeNull()
    expect(navigateSpy).toHaveBeenCalledWith("/et/courses")
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
    const description = await screen.findByRole("textbox", { name: "課程描述" })
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
          chapters: [{ chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] }],
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

  it("新增模式顯示全部基本資料欄位且為空白 / 預設值", async () => {
    renderNewEditor()
    expect(await screen.findByRole("heading", { name: "新增課程" })).toBeInTheDocument()
    expect(screen.getByRole("textbox", { name: "課程名稱" })).toHaveValue("")
    // 起訖採 DateTimePicker（下拉式選擇器 + 確認 / 取消），非原生 datetime-local。
    // MUI 的 label 會同時出現在 <label> 與 fieldset <legend>，故以 role + 精確名稱查。
    // 起訖採 DateTimePicker（下拉式選擇器 + 確認 / 取消），非原生 datetime-local。
    // 它渲染為多層帶 label 的容器（無 role、無 value），逐一斷言「存在且空白」意義不大；
    // 「未填即送出 null」改由下方「一次送出」測試以行為驗證。
    expect(screen.getAllByLabelText("課程起始時間").length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText("課程訖止時間").length).toBeGreaterThan(0)
    expect(screen.getByRole("textbox", { name: "課程描述" })).toHaveValue("")
    expect(screen.getByLabelText("本課程需線下核可")).not.toBeChecked()
    expect(screen.getByLabelText("狀態")).toHaveValue("草稿")
  })

  it("「儲存並發布」按鈕呈現但停用（發布屬 #204）", async () => {
    renderNewEditor()
    const publish = await screen.findByRole("button", { name: "儲存並發布" })
    expect(publish).toBeDisabled()
    // 不可先讓它能按：發布檢核之「≥ 1 教材」「配分 = 100」要到 #203 才驗得了，
    // 而發布會觸發標籤自動邀請＋寄信，等於通知全體學員一門空課程。
    expect(screen.getByRole("button", { name: "儲存草稿" })).toBeEnabled()
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

// ── ET02 關閉與再開課（US11 / #288）──────────────────────────────────────────

/** 以指定狀態與擁有權覆蓋課程詳細——關閉 / 再開課按鈕全由這兩者決定。 */
function useCourse(status: string, { isOwner = true }: { isOwner?: boolean } = {}) {
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
        tag_ids: [2],
        chapters: [],
        invitation_code: isOwner ? "01234567" : null,
      }),
    ),
  )
}

describe("ET02 課程關閉與再開課", () => {
  it("已發布課程顯示「關閉課程」，不顯示「再開課」", async () => {
    useCourse("PUBLISHED")
    renderEditor()
    expect(await screen.findByRole("button", { name: "關閉課程" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
  })

  it("已關閉課程顯示「再開課」，不顯示「關閉課程」與「邀請學員」", async () => {
    // AC 5 / FR-ET-US11-07：關閉期間不可邀請學員，故按鈕一併收起（後端另以
    // ET_INVITE_004 把關）。再開課後 status 回 PUBLISHED，兩顆按鈕自然互換。
    useCourse("CLOSED")
    renderEditor()

    expect(await screen.findByRole("button", { name: "再開課" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "邀請學員" })).not.toBeInTheDocument()
  })

  it("已關閉提示明確寫出「課程內容仍可編輯」（AC 6）", async () => {
    // 少了這句，教師會以為關閉後這頁是唯讀的而不敢改——AC 6 的整個用意就是讓他能在
    // 關閉期間整理教材再開課。
    useCourse("CLOSED")
    renderEditor()
    expect(await screen.findByText(/此課程已關閉/)).toBeInTheDocument()
    expect(screen.getByText(/課程內容仍可編輯/)).toBeInTheDocument()
  })

  it("草稿不顯示關閉 / 再開課（草稿沒有學員也沒有邀請碼，關閉沒有語意）", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
  })

  it("非擁有者（檢視模式）不顯示關閉 / 再開課", async () => {
    useCourse("PUBLISHED", { isOwner: false })
    renderEditor()
    await screen.findByText(/檢視模式/)
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
  })

  it("關閉前先確認，且確認內容說明學員仍可唯讀回看與可再開課", async () => {
    // 關閉會立刻影響所有在籍學員。可逆這件事也要說，否則教師會誤以為這是不可回復的
    // 動作而不敢按。
    const user = userEvent.setup()
    useCourse("PUBLISHED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))

    expect(await screen.findByText(/已加入的學員仍可唯讀回看內容與成績/)).toBeInTheDocument()
    expect(screen.getByText(/課程內容於關閉期間仍可編輯，之後可再開課/)).toBeInTheDocument()
  })

  it("確認關閉時送出當前版本（樂觀鎖）", async () => {
    const user = userEvent.setup()
    let body: unknown
    useCourse("PUBLISHED")
    server.use(
      http.post("/api/et/courses/:courseId/close", async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          course_id: 1,
          status: "CLOSED",
          open_start_at: "2026-09-01T00:00:00Z",
          open_end_at: "2027-09-30T00:00:00Z",
          closed_at: "2026-09-09T03:00:00Z",
          version: 6,
        })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))
    await user.click(await screen.findByRole("button", { name: "確認關閉" }))

    await waitFor(() => expect(body).toEqual({ version: 5 }))
    expect(await screen.findByText("課程已關閉")).toBeInTheDocument()
  })

  it("關閉遇版本衝突時顯示衝突視窗而非成功訊息", async () => {
    const user = userEvent.setup()
    useCourse("PUBLISHED")
    server.use(
      http.post("/api/et/courses/:courseId/close", () =>
        HttpResponse.json(
          { error_code: "ET_LOCK_001", error_message: "資料已被其他人修改" },
          { status: 409 },
        ),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))
    await user.click(await screen.findByRole("button", { name: "確認關閉" }))

    expect(await screen.findByText("內容已被其他裝置變更，請重新整理後再儲存。")).toBeInTheDocument()
    expect(screen.queryByText("課程已關閉")).not.toBeInTheDocument()
  })

  it("再開課視窗可開啟與取消（時間欄位之填值見 ReopenCourseDialog.test.tsx）", async () => {
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()

    await user.click(await screen.findByRole("button", { name: "再開課" }))
    expect(await screen.findByRole("button", { name: "確認再開課" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "確認再開課" })).not.toBeInTheDocument(),
    )
  })

  it("再開課送出的 body 只有後端 ReopenCourseReq 接受的三個欄位", async () => {
    // 🔴 迴歸測試。後端 `ReopenCourseReq` 原本繼承 `_CourseFields`，連 `course_name` 的
    // 必填性一起繼承了，而前端從不送它 → 真實操作每次都 422，AC 8 完全不可用。
    //
    // 這個缺陷躲過三層測試：後端整合測試自己多塞 `course_name`、MSW handler 不驗 body、
    // ReopenCourseDialog 測試用假的 `onSubmit`。**沒有一層驗過「前端組出的 payload
    // 與後端 schema 相符」**，所以這裡直接斷言送出的鍵集合。
    //
    // 走 service 層而非 UI：`DateTimePicker` 在 jsdom 無法以 userEvent 可靠填值（本專案
    // 無任何測試做到過），而缺陷在 payload 的形狀、不在選擇器的互動。頁面把哪些值放進
    // payload 由 `ReopenPayload` 的型別在 `tsc -b` 時保證。
    //
    // ⚠️ 對應的後端測試是
    // `test_et_course_close_reopen.py::TestReopen::test_以前端實際送出的欄位再開課`，
    // 兩者是同一份契約的兩端，改動任一邊請同步。
    let body: Record<string, unknown> | undefined
    server.use(
      http.post("/api/et/courses/:courseId/reopen", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          course_id: 1,
          status: "PUBLISHED",
          open_start_at: "2026-10-01T00:00:00Z",
          open_end_at: "2027-10-31T00:00:00Z",
          closed_at: "2026-09-09T03:00:00Z",
          version: 6,
        })
      }),
    )

    await coursesApi.reopen(1, {
      open_start_at: "2026-10-01T00:00:00.000Z",
      open_end_at: "2027-10-31T00:00:00.000Z",
      version: 5,
    })

    expect(Object.keys(body ?? {}).sort()).toEqual(["open_end_at", "open_start_at", "version"])
  })

  it("關閉送出的 body 只有 version", async () => {
    let body: Record<string, unknown> | undefined
    server.use(
      http.post("/api/et/courses/:courseId/close", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          course_id: 1,
          status: "CLOSED",
          open_start_at: null,
          open_end_at: null,
          closed_at: "2026-09-09T03:00:00Z",
          version: 6,
        })
      }),
    )

    await coursesApi.close(1, 5)

    expect(body).toEqual({ version: 5 })
  })
})
