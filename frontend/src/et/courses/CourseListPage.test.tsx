import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseListPage } from "./CourseListPage"
import { KEYWORD_MAX_LENGTH } from "./schemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
let searchParams = new URLSearchParams()
const setSearchParams = vi.fn((next: URLSearchParams | Record<string, string>) => {
  searchParams = next instanceof URLSearchParams ? next : new URLSearchParams(next)
})

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigate,
    useSearchParams: () => [searchParams, setSearchParams] as const,
  }
})

/** 覆寫清單回應；`data` 為空即模擬零筆。 */
function mockList(data: unknown[]) {
  server.use(
    http.get("/api/et/courses", () =>
      HttpResponse.json({ data, meta: { total: data.length, page: 1, limit: 12, total_pages: 1 } }),
    ),
  )
}

beforeEach(() => {
  navigate.mockReset()
  setSearchParams.mockReset()
  searchParams = new URLSearchParams()
})

describe("ET01 課程列表", () => {
  it("以卡片呈現課程，含章節數與在籍學員數", async () => {
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.getByText("5 章節")).toBeInTheDocument()
    expect(screen.getByText("28 位學員")).toBeInTheDocument()
    expect(screen.getByText("護理師")).toBeInTheDocument()
  })

  it("「我建立的」看得到草稿（AC 1）", async () => {
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("草稿課")).toBeInTheDocument()
    expect(screen.getByText("草稿")).toBeInTheDocument()
  })

  it("他人課程顯示「檢視」標籤，自己的不顯示（AC 7 / 8）", async () => {
    searchParams = new URLSearchParams({ scope: "all" })
    renderWithProviders(<EtCourseListPage />)

    await screen.findByText("捐血人健康評估標準教學")
    // 兩張卡片，只有他人那張帶「檢視」
    expect(screen.getAllByText("檢視")).toHaveLength(1)
  })

  it("點卡片導向該課程（自己的進編輯、他人的進唯讀由 ET02 判定）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)

    await user.click(await screen.findByText("採血作業新進人員訓練"))

    expect(navigate).toHaveBeenCalledWith("/et/courses/11")
  })

  it("篩選無結果顯示 ET-MSG-ET01-001", async () => {
    mockList([])
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)

    await user.type(screen.getByLabelText("關鍵字"), "不存在的課")

    expect(await screen.findByText("查無符合條件之課程")).toBeInTheDocument()
  })

  it("尚未建立任何課程時用**另一組**文案，不說「查無符合條件」", async () => {
    // 對一個還沒建過課的新教師說「查無符合條件之課程」，會讓他以為自己篩錯了
    mockList([])
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("您尚未建立任何課程")).toBeInTheDocument()
    expect(screen.queryByText("查無符合條件之課程")).not.toBeInTheDocument()
  })

  it("標籤下拉含已停用者並標示出來", async () => {
    // 停用標籤仍可用於篩選（要查得到歷史課程），但要讓教師知道它已經不能再掛
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)
    await screen.findByText("採血作業新進人員訓練")

    await user.click(screen.getByLabelText("受訓單位標籤"))

    expect(await screen.findByText("已裁撤單位（已停用）")).toBeInTheDocument()
  })

  it("「建立者」篩選只在「全部課程」出現，且不佔位", async () => {
    const { unmount } = renderWithProviders(<EtCourseListPage />)
    await screen.findByText("採血作業新進人員訓練")
    expect(screen.queryByLabelText("建立者")).not.toBeInTheDocument()

    // 一定要先 unmount：`searchParams` 是模組層變數，第一棵樹之後只要有任何一次
    // re-render 就會讀到改動後的值，也長出一個「建立者」，斷言就會撞到兩個節點
    unmount()
    searchParams = new URLSearchParams({ scope: "all" })
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByLabelText("建立者")).toBeInTheDocument()
  })

  it("送出的查詢參數恰為契約所列，關鍵字卡在後端同一個上限", async () => {
    // 前後端各有一份查詢參數型別，兩邊都不驗對方。沒有這條，參數改名或加上限會表現成
    // 「篩選送出後 422 或被靜默忽略」，而前端測試、MSW、後端測試各自都綠。
    // 對應的後端斷言：test_et_course_list.py::test_前端送出的完整參數集合可通過後端驗證
    const seen: URLSearchParams[] = []
    server.use(
      http.get("/api/et/courses", ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 12, total_pages: 1 } })
      }),
    )
    renderWithProviders(<EtCourseListPage />)

    await waitFor(() => expect(seen.length).toBeGreaterThan(0))

    expect([...seen[0].keys()].sort()).toEqual(["limit", "page", "scope"])
    // 關鍵字上限與後端 Query(max_length=100) 同源；放寬後端時這裡會提醒一起改
    expect(screen.getByLabelText("關鍵字")).toHaveAttribute("maxLength", String(KEYWORD_MAX_LENGTH))
    expect(KEYWORD_MAX_LENGTH).toBe(100)
  })

  it("選定建立者後選單不塌成一個人，還能直接改選別人", async () => {
    // 選單來源是當前結果；篩選後結果只剩被選中的那位，若照樣重算，使用者想改選別人
    // 就得先切回「全部」再選一次
    searchParams = new URLSearchParams({ scope: "all" })
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)
    await screen.findByText("捐血人健康評估標準教學")

    await user.click(screen.getByLabelText("建立者"))
    await user.click(await screen.findByRole("option", { name: "林助教" }))
    await waitFor(() => expect(screen.queryByText("採血作業新進人員訓練")).not.toBeInTheDocument())

    await user.click(screen.getByLabelText("建立者"))
    expect(await screen.findByRole("option", { name: "陳大華" })).toBeInTheDocument()
  })

  it("切換分頁寫進 URL query，重新整理不會跳回預設", async () => {
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)
    await screen.findByText("採血作業新進人員訓練")

    await user.click(screen.getByRole("tab", { name: "全部課程" }))

    await waitFor(() => expect(setSearchParams).toHaveBeenCalledWith({ scope: "all" }))
  })
})
