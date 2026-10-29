// #836（2026-10-28 使用者裁示）：ET05 已發布／已關閉課程不再於頁面上方常駐邀請碼橫幅。
//
// 該橫幅原是 #247 補 #204 之缺口——當時邀請碼只在發布當下的 PublishDialog 出現一次，
// 教師關掉視窗就永久拿不回來。缺口現已由「邀請學員」視窗的「邀請碼」頁籤補上，橫幅成為
// 重複入口。已關閉課程則本就禁止邀請學員，不需呈現邀請碼。

import { screen, within } from "@testing-library/react"
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

const CODE = "01234567"

/** 擁有者視角的課程；`closed` 為 true 時比照已關閉（狀態與 `is_closed` 一致）。 */
function mockCourse(closed: boolean) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status: closed ? "CLOSED" : "PUBLISHED",
        open_start_at: "2026-01-01T00:00:00Z",
        open_end_at: "2099-12-31T00:00:00Z",
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        is_closed: closed,
        has_pending_changes: false,
        // 後端只對 owner 回傳本欄位；有碼才可能渲染橫幅，故兩個情境都給值
        invitation_code: CODE,
        audiences: [],
        chapters: [],
      }),
    ),
  )
}

/**
 * 橫幅不存在的兩道斷言。
 *
 * ⚠️ 只驗標籤不夠：若有人改了標籤文字卻把邀請碼留在畫面上，只驗標籤的測試照樣綠。
 * 兩條一起才涵蓋「這組碼沒有出現在頁面上」。
 */
function expectNoBanner() {
  expect(screen.queryByText("課程邀請碼：")).not.toBeInTheDocument()
  expect(screen.queryByText(CODE)).not.toBeInTheDocument()
}

describe("ET05 不再常駐邀請碼橫幅（#836）", () => {
  it("已發布課程：頁面上沒有邀請碼，但「邀請學員」入口仍在", async () => {
    mockCourse(false)
    renderWithProviders(<EtCourseEditorPage />)

    // 正向錨點：課程確實已載入且為擁有者視角，否則「什麼都沒有」也會讓否定斷言通過
    expect(await screen.findByRole("button", { name: "邀請學員" })).toBeInTheDocument()
    expectNoBanner()
  })

  it("已發布課程：邀請碼改由「邀請學員」視窗的「邀請碼」頁籤取得", async () => {
    // 🔴 本條是移除橫幅的正當性所在。拿掉橫幅的理由是「這條路徑可以取代它」——
    // 該路徑若壞掉，移除就只是功能損失。
    const user = userEvent.setup()
    mockCourse(false)
    renderWithProviders(<EtCourseEditorPage />)

    await user.click(await screen.findByRole("button", { name: "邀請學員" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("tab", { name: "邀請碼" }))

    expect(await within(dialog).findByText(CODE)).toBeInTheDocument()
    // #359 第 2 項的守門隨邀請碼一起搬家：原本釘在編輯頁橫幅（`reopen.test.tsx`，隨橫幅一併
    // 移除），現在邀請碼的所在地是本視窗，會有人在這裡補上那句說明的也是這裡。規則本身未變
    // ——「發布後沿用同一組」由 ET05 手冊承載，畫面不寫。
    // ℹ️ 發布當下的結果視窗另有自己的同名守門（`PublishDialog.test.tsx`），不受本次影響。
    expect(within(dialog).queryByText(/永久不可變更/)).not.toBeInTheDocument()
  })

  it("已關閉課程：頁面上沒有邀請碼", async () => {
    mockCourse(true)
    renderWithProviders(<EtCourseEditorPage />)

    // 正向錨點取「更新並重開課」而非課程名稱：已關閉課程不顯示「邀請學員」鈕，而表單預帶
    // 與狀態無關（任何狀態都會帶入課程名稱），用它只證明資料載入、證明不了畫面真的走到
    // `is_closed` 分支——該鈕是已關閉課程專屬的底部動作（#720）。
    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeInTheDocument()
    expectNoBanner()
  })
})
