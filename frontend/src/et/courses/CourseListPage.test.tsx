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

  it("點卡片導向該課程（自己的進編輯、他人的進唯讀由 ET05 判定）", async () => {
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

  it("單位下拉含已停用者並標示出來", async () => {
    // 停用標籤仍可用於篩選（要查得到歷史課程），但要讓教師知道它已經不能再掛
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)
    await screen.findByText("採血作業新進人員訓練")

    await user.click(screen.getByLabelText("單位"))

    expect(await screen.findByText("已裁撤單位（已停用）")).toBeInTheDocument()
    // 兩欄各取一類：職位不得混進單位下拉
    expect(screen.queryByRole("option", { name: "護理師" })).not.toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "全單位" })).toBeInTheDocument()
  })

  it("單位與職位兩欄送出的參數名與後端契約一致（#538）", async () => {
    // 上一條契約測試只驗「沒選任何篩選」時的參數集合——篩選欄位的參數名從來沒被驗過，
    // 改名的話它照樣綠。對應的後端斷言同為 test_前端送出的完整參數集合可通過後端驗證
    const seen: URLSearchParams[] = []
    server.use(
      http.get("/api/et/courses", ({ request }) => {
        seen.push(new URL(request.url).searchParams)
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 12, total_pages: 1 } })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtCourseListPage />)
    await waitFor(() => expect(seen.length).toBeGreaterThan(0))

    await user.click(screen.getByLabelText("單位"))
    await user.click(await screen.findByRole("option", { name: "全單位" }))
    await user.click(screen.getByLabelText("職位"))
    await user.click(await screen.findByRole("option", { name: "護理師" }))

    await waitFor(() => expect(seen.at(-1)?.get("tag_id")).toBe("2"))
    const last = seen.at(-1)!
    expect(last.get("unit_tag_id")).toBe("101")
    expect([...last.keys()].sort()).toEqual(["limit", "page", "scope", "tag_id", "unit_tag_id"])
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

/**
 * 純 ET 管理者（無教師角色）的分頁與預設值（#463）。
 *
 * 手測回報：「如果只有 ET 管理者的權限，課程列表只需要看到全部課程，不需要呈現『我建立的』」。
 * 建課需 `ET_TEACHER`，所以純管理者的「我建立的」是空的——而預設 scope 正是 `mine`，
 * 他一進頁面就停在一個永遠沒有東西的分頁。
 */
describe("課程列表：純 ET 管理者（#463）", () => {
  /** 設定 `can_create_course`（＝具教師角色）；其餘能力維持可管理。 */
  function asRole(isTeacher: boolean) {
    server.use(
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({
          can_create_course: isTeacher,
          can_manage_courses: true,
          can_track_students: isTeacher,
          can_learn: false,
        }),
      ),
    )
  }

  it("純管理者看不到「我建立的」分頁", async () => {
    asRole(false)
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("全部課程")).toBeInTheDocument()
    expect(screen.queryByText("我建立的")).not.toBeInTheDocument()
  })

  it("🔴 等 capabilities 的期間顯示載入中，**不得**閃出假的空狀態", async () => {
    // ⚠️ 這是 #463 的修法差點自己引入的缺陷，而且**影響所有使用者**、不限管理者。
    //
    // `usePagedQuery` 把 `isPending` 收斂成 `enabled && query.isPending`
    //（`hooks/usePagedQuery.ts` 的既有設計，為了讓未啟用的頁籤不顯示載入中）。
    // 於是 `enabled: capabilities !== undefined` 在等待期間會讓 `isPending` 為 **false**
    // 而 `data` 仍是 `undefined` → `courses.length === 0` → 直接渲染
    //「您尚未建立任何課程」。那是一句**假話**，而且正是本 issue 要消滅的那種閃爍。
    //
    // MSW 幾乎同步回應，所以要**刻意延遲** capabilities 才看得到這個窗口。
    server.use(
      http.get("/api/et/courses/capabilities", async () => {
        await new Promise((r) => setTimeout(r, 80))
        return HttpResponse.json({
          can_create_course: true,
          can_manage_courses: true,
          can_track_students: true,
          can_learn: false,
        })
      }),
    )
    mockList([])
    renderWithProviders(<EtCourseListPage />)

    expect(screen.getByRole("progressbar")).toBeInTheDocument()
    expect(screen.queryByText("您尚未建立任何課程")).not.toBeInTheDocument()
    expect(screen.queryByText("目前沒有已發布的課程")).not.toBeInTheDocument()

    // 等到真的查完之後，空狀態才該出現
    expect(await screen.findByText("您尚未建立任何課程")).toBeInTheDocument()
  })

  it("純管理者手動輸入 ?scope=mine 時，網址會被更正為全部課程", async () => {
    // 他沒有分頁可切，`changeScope` 永遠不會被呼叫——網址若留著 `scope=mine`，
    // 貼給同事或自己重整時，網址說的與畫面顯示的是兩件事。
    asRole(false)
    searchParams = new URLSearchParams({ scope: "mine" })
    renderWithProviders(<EtCourseListPage />)

    await screen.findByText("全部課程")
    await waitFor(() => expect(setSearchParams).toHaveBeenCalled())
  })

  it("教師兩個分頁都看得到——本次改動不得影響他", async () => {
    asRole(true)
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("我建立的")).toBeInTheDocument()
    expect(screen.getByText("全部課程")).toBeInTheDocument()
  })

  it("🔴 純管理者的查詢一律送 scope=all，不得先打一次 scope=mine", async () => {
    // 預設 scope 是 `mine`，而 `capabilities` 是非同步的。若不等它回來就發查詢，
    // 管理者會先拿到一個空清單再被換掉——畫面閃一下「查無課程」，而那是假的。
    asRole(false)
    const scopes: string[] = []
    server.use(
      http.get("/api/et/courses", ({ request }) => {
        scopes.push(new URL(request.url).searchParams.get("scope") ?? "")
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 12, total_pages: 0 } })
      }),
    )
    renderWithProviders(<EtCourseListPage />)

    await screen.findByText("全部課程")
    await waitFor(() => expect(scopes.length).toBeGreaterThan(0))
    expect(scopes).not.toContain("mine")
  })

  it("教師的預設查詢仍是 scope=mine", async () => {
    asRole(true)
    const scopes: string[] = []
    server.use(
      http.get("/api/et/courses", ({ request }) => {
        scopes.push(new URL(request.url).searchParams.get("scope") ?? "")
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 12, total_pages: 0 } })
      }),
    )
    renderWithProviders(<EtCourseListPage />)

    await waitFor(() => expect(scopes).toContain("mine"))
  })

  it("純管理者不顯示「點擊自己建立之課程進入編輯模式」——他沒有自己建立的課程", async () => {
    // 那句話對他恆為假：他建不了課程，所有課程對他都是唯讀（編輯由 `ensure_owner` 把關）。
    //
    // ⚠️ **不可用 `queryByText(/進入編輯模式/)`**：那段說明被 `<strong>` 切成數段，
    // 跨元素的正則**永遠找不到**——於是不論有沒有那句話，斷言都會通過。本條最初就是
    // 這樣寫的，它在實作之前就綠了。改為比對單一 `<strong>` 的完整文字。
    asRole(false)
    renderWithProviders(<EtCourseListPage />)

    await screen.findByText("全部課程")
    expect(screen.queryByText("編輯模式")).not.toBeInTheDocument()
  })

  it("教師仍看得到編輯／檢視模式的說明——上一條的對照組", async () => {
    // 少了這條，「不顯示」那條就算因為選擇器寫錯而永遠通過也沒人會發現。
    asRole(true)
    renderWithProviders(<EtCourseListPage />)

    expect(await screen.findByText("編輯模式")).toBeInTheDocument()
  })
})
