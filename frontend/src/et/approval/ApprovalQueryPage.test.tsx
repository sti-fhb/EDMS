import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { EtApprovalQueryPage } from "./ApprovalQueryPage"

/**
 * 設定登入者身分——本頁的分流同時取自**兩支端點**，兩支都要覆寫。
 *
 * ⚠️ `capabilities` 決定「教師視角還是學員視角」，`module-summary` 的 `et.is_admin`
 * 決定「教師視角裡要不要顯示範圍提示」。只設前者的話，預設 handler 會讓每個人都是
 * 管理者（`is_admin: true`），教師專屬的提示就永遠測不到。
 */
function asRole(role: "teacher" | "admin" | "student") {
  const canManage = role !== "student"
  server.use(
    http.get("/api/et/courses/capabilities", () =>
      HttpResponse.json({
        can_create_course: role === "teacher",
        can_manage_courses: canManage,
        can_learn: role === "student",
      }),
    ),
    http.get("/api/dp/user/module-summary", () =>
      HttpResponse.json({
        et: { has_role: true, is_admin: role === "admin" },
        dm: { has_role: false, is_admin: false },
      }),
    ),
  )
}

const EMPTY = { data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }

describe("ET10 核可查詢：教師 / 管理者視角", () => {
  it("輸入姓名查詢後列出核可紀錄，含課程、結果、核可人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // fixture 三列同屬林佳蓉，故鎖定其中一列而非全頁比對
    const row = (await screen.findByText("採血作業新進人員訓練")).closest("tr")!
    expect(within(row).getByText("林佳蓉")).toBeInTheDocument()
    expect(within(row).getByText("王主任")).toBeInTheDocument()
    expect(within(row).getByText("通過")).toBeInTheDocument()
  })

  it("已撤銷的紀錄標示已撤銷並列出原因與撤銷人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    const row = (await screen.findByText("血品安全與品保概論")).closest("tr")!
    expect(within(row).getByText("已撤銷")).toBeInTheDocument()
    expect(within(row).getByText(/核可對象誤植/)).toBeInTheDocument()
    expect(within(row).getByText(/李管理員/)).toBeInTheDocument()
  })

  it("🔴 教師視角常駐範圍提示——那是 SA 裁示 C 的配套，不是可選的 UX 潤飾", async () => {
    // 少了它，教師看到某門課沒出現時分不清是「還沒考」還是「考了沒過」。
    // 裁示 C 讓同一張表裡混了兩種範圍，提示是唯一讓教師知道這件事的地方。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    const hint = await screen.findByText(/僅顯示您所開設的課程/)
    expect(hint).toBeInTheDocument()
    // SA 2026-09-21 追加裁示：他人課程的考核備註也被遮蔽，提示必須一併涵蓋——
    // 否則教師看到通過卻沒備註時會以為核可人沒寫，而不是被遮蔽了。
    expect(hint).toHaveTextContent("考核備註")
  })

  it("查無資料顯示空狀態提示（ET-MSG-ET10-001）", async () => {
    asRole("teacher")
    server.use(http.post("/api/et/approvals/search", () => HttpResponse.json(EMPTY)))
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "查無此人")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText(/查無符合條件的核可紀錄/)).toBeInTheDocument()
    // 🔴 教師必須被告知「可能不在您的可見範圍內」：本頁用於「排班前確認某人受訓完整
    // 與否」，而「查無」會被讀成「這個人沒受過訓」——那是方向最危險的假陰性，且
    // 可見範圍分流（SA Q1 裁示 C）讓它在正式使用時一定會發生。
    expect(screen.getByText(/可能是該紀錄不在您的可見範圍內/)).toBeInTheDocument()
  })

  it("管理者的空狀態不提可見範圍（他沒有範圍限制，那句話對他是錯的）（#436）", async () => {
    // ⚠️ 反向斷言。對管理者說「可能不在您的可見範圍內」會讓他去找一個不存在的原因
    // ——他的 `visible_clause` 是 `true()`，查不到就是真的沒有。
    asRole("admin")
    server.use(http.post("/api/et/approvals/search", () => HttpResponse.json(EMPTY)))
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "查無此人")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText(/查無符合條件的核可紀錄/)).toBeInTheDocument()
    expect(screen.queryByText(/可見範圍/)).not.toBeInTheDocument()
  })

  it("Email 與姓名共用同一欄，同樣送進 body（#436）", async () => {
    // ⚠️ 標籤改了、後端也支援了，但**沒有東西驗證前端真的把 Email 送出去**——
    // 少了這條，把輸入框綁錯 state 或在送出前過濾掉 `@` 都不會有任何東西變紅。
    //
    // 🔴 Email 是個資、且比姓名更能唯一定位一個人，故 #391 的「不得進網址」對它
    // **更**適用，不是更寬鬆。此處一併釘住。
    asRole("teacher")
    const seen: { url?: string; body?: { keyword?: string } } = {}
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        seen.url = request.url
        seen.body = (await request.json()) as NonNullable<typeof seen.body>
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "lin@edms.local")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    await waitFor(() => expect(seen.body?.keyword).toBe("lin@edms.local"))
    expect(seen.url).not.toContain("lin@edms.local")
    expect(seen.url).not.toContain(encodeURIComponent("lin@edms.local"))
  })

  it("關鍵字走 request body，網址裡沒有（#391）", async () => {
    // 🔴 本端點是 POST 的唯一理由：`keyword` 必定是姓名或 Email（皆為個資），而網址會被
    // nginx `error_log` 與 Cloudflare 的請求日誌記下來（前者格式不可自訂、後者不在
    // 本系統掌控範圍），body 不會。
    //
    // ⛔ 若有人為了「比較 RESTful」把 service 改回 `http.get(url, { params })`，
    // 姓名就回到網址裡，而**畫面行為完全正常**——沒有任何東西看起來壞掉。
    // 本條與後端的 `test_姓名走query_string不被接受` 是同一道紅線的兩端。
    asRole("teacher")
    const seen: { url?: string; body?: { keyword?: string } } = {}
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        seen.url = request.url
        seen.body = (await request.json()) as NonNullable<typeof seen.body>
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林佳蓉")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    await waitFor(() => expect(seen.body?.keyword).toBe("林佳蓉"))
    expect(seen.url).not.toContain("林佳蓉")
    expect(seen.url).not.toContain("keyword")
    // 連編碼過的形式也不行——`encodeURIComponent` 後是看不出來的百分號序列
    expect(seen.url).not.toContain(encodeURIComponent("林佳蓉"))
  })

  it("關鍵字與課程皆未給時不送出請求（#439，原 SA Q2 裁示 A）", async () => {
    asRole("teacher")
    let called = false
    server.use(
      http.post("/api/et/approvals/search", () => {
        called = true
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.click(await screen.findByRole("button", { name: "查詢" }))

    expect(await screen.findByText("請輸入姓名或 Email，或選擇課程")).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it("只打空白且未選課程也視為未給", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "   ")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("請輸入姓名或 Email，或選擇課程")).toBeInTheDocument()
  })

  it("查詢前不顯示空狀態——那會讓人以為已經查過且查無資料", async () => {
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名或 Email")
    expect(screen.queryByText("查無符合條件的核可紀錄")).not.toBeInTheDocument()
  })

  it("只選課程、不填關鍵字即可查詢，且 course_id 進 body（#439）", async () => {
    // 🔴 這是 #439 的本體：使用者常常**正是不知道有誰可以查**。
    // 一併釘住「keyword 不得變成空字串送出去」——後端以 `if keyword:` 判斷，空字串
    // 雖然也 falsy，但送一個空字串代表前端沒有真的把「未填」表達出來。
    asRole("teacher")
    const seen: { body?: { keyword?: string; course_id?: number } } = {}
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        seen.body = (await request.json()) as NonNullable<typeof seen.body>
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.click(await screen.findByLabelText("課程"))
    await user.click(await screen.findByRole("option", { name: "採血作業新進人員訓練" }))
    await user.click(screen.getByRole("button", { name: "查詢" }))

    await waitFor(() => expect(seen.body?.course_id).toBe(11))
    expect(seen.body?.keyword).toBeUndefined()
  })

  it("關鍵字與課程同時給時，兩者都進 body（#439）", async () => {
    // ⚠️ 兩個欄位各自有一段 `|| undefined` / `=== "" ? undefined` 的轉換，而「只給一個」
    // 的測試各自只走過其中一段——**同時給**才驗得到兩段併存時都正確。
    asRole("teacher")
    const seen: { body?: { keyword?: string; course_id?: number } } = {}
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        seen.body = (await request.json()) as NonNullable<typeof seen.body>
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林佳蓉")
    await user.click(await screen.findByLabelText("課程"))
    await user.click(await screen.findByRole("option", { name: "採血作業新進人員訓練" }))
    await user.click(screen.getByRole("button", { name: "查詢" }))

    await waitFor(() => expect(seen.body?.course_id).toBe(11))
    expect(seen.body?.keyword).toBe("林佳蓉")
  })

  it("課程下拉的選項來自 filter-courses，不是 ET01 的課程清單（#439）", async () => {
    // ⛔ 走 `GET /et/courses` 會壞在管理者身上：`scope=all` 排除已結束的課程，而核可
    // 紀錄絕大多數正落在那些課上——最相關的課會全部不在下拉裡，且畫面不會說明任何事。
    //
    // 本條以「那支端點沒被呼叫」+「下拉內容來自 filter-courses」兩面釘住。
    asRole("teacher")
    let listCalled = false
    server.use(
      http.get("/api/et/courses", () => {
        listCalled = true
        return HttpResponse.json(EMPTY)
      }),
      http.get("/api/et/approvals/filter-courses", () =>
        HttpResponse.json([{ course_id: 77, course_name: "已結束的舊課程" }]),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.click(await screen.findByLabelText("課程"))
    expect(await screen.findByRole("option", { name: "已結束的舊課程" })).toBeInTheDocument()
    expect(listCalled).toBe(false)
  })

  it("🔴 課程清單載入失敗時說「載入失敗」，**不得**說「尚無核可紀錄」（#439）", async () => {
    // 後者是一句**假話**，而且比缺陷本身更糟——教師會據此以為系統裡真的沒有核可紀錄，
    // 而不是「剛才沒載到，重整一下」。ET03 的課程下拉踩過同一個坑（#390 的回歸）。
    asRole("teacher")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json({}, { status: 500 })))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("課程清單載入失敗，請重新整理後再試")).toBeInTheDocument()
    expect(screen.queryByText(/尚無核可紀錄/)).not.toBeInTheDocument()
  })

  it("教師沒有任何可選課程時說明原因，而不是給一個打得開卻空的下拉（#439）", async () => {
    asRole("teacher")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json([])))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("您開設的課程尚無核可紀錄")).toBeInTheDocument()
  })

  it("管理者的空下拉不提「您開設的課程」——他沒有自己的課，那句話對他是錯的（#439）", async () => {
    // 與 #436 的空狀態同一條理由：對管理者說一個不適用於他的原因，會讓他去找一個
    // 不存在的問題。
    asRole("admin")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json([])))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("系統中尚無核可紀錄")).toBeInTheDocument()
    expect(screen.queryByText(/您開設的課程/)).not.toBeInTheDocument()
  })

  it("🔴 查詢失敗顯示錯誤，**不得**渲染成「查無符合條件」", async () => {
    // 本頁的使用情境是排班前確認某人受訓完整與否，「查無紀錄」會被讀成「沒受過訓」
    // ——那是方向最危險的假陰性。最容易撞到的是 429（查詢與核可寫入共用同一個分桶）。
    asRole("teacher")
    server.use(
      http.post("/api/et/approvals/search", () =>
        HttpResponse.json({ error_code: "COMMON_429", error_message: "操作過於頻繁，請稍後再試" }, { status: 429 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("操作過於頻繁，請稍後再試")).toBeInTheDocument()
    expect(screen.queryByText("查無符合條件的核可紀錄")).not.toBeInTheDocument()
  })
})

describe("ET10 核可查詢：學員視角", () => {
  it("🔴 載入失敗顯示錯誤，**不得**渲染成「尚無已通過核可的課程」", async () => {
    asRole("student")
    server.use(
      http.get("/api/et/approvals/mine", () =>
        HttpResponse.json({ error_code: "COMMON_500", error_message: "系統發生錯誤" }, { status: 500 }),
      ),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("系統發生錯誤")).toBeInTheDocument()
    expect(screen.queryByText("您目前尚無已通過核可的課程")).not.toBeInTheDocument()
  })

  it("僅顯示自己已通過的課程，且不出現查詢框", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.queryByLabelText("學員姓名")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "查詢" })).not.toBeInTheDocument()
  })

  it("不顯示教師視角的範圍提示", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByText("採血作業新進人員訓練")
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("無已通過課程時顯示空狀態（ET-MSG-ET10-002）", async () => {
    asRole("student")
    server.use(http.get("/api/et/approvals/mine", () => HttpResponse.json(EMPTY)))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("您目前尚無已通過核可的課程")).toBeInTheDocument()
  })
})

describe("ET10 核可查詢：共通", () => {
  it("🔴 任一視角都不得提供下載或列印（FR-ET-US17-05）", async () => {
    // 客戶 2026-07-17 明確確認**不需要**核可證明 / 結業證書。
    for (const role of ["teacher", "student"] as const) {
      asRole(role)
      const { unmount } = renderWithProviders(<EtApprovalQueryPage />)
      await waitFor(() => expect(screen.queryByText("載入中…")).not.toBeInTheDocument())

      for (const name of [/下載/, /列印/, /證明/, /證書/, /匯出/]) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
        expect(screen.queryByText(name)).not.toBeInTheDocument()
      }
      unmount()
    }
  })

  it("管理者視角不顯示教師專屬的範圍提示", async () => {
    // 🔴 管理者沒有範圍限制，對他顯示「僅顯示您所開設的課程」是錯的資訊。
    // ⚠️ 判定來源是 `module-summary.et.is_admin`，不是 `capabilities`——同時具教師與
    // 管理者身分者 `can_create_course` 也是 true，用它推會把他誤判成非管理者。
    asRole("admin")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByLabelText("學員姓名或 Email")).toBeInTheDocument()
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("🔴 `module-summary` 未回來前不渲染任何視角——避免管理者閃現不適用的提示", async () => {
    // 只等 `capabilities` 的話，整頁重新載入時它可能先回來，此時 `summary` 還是
    // undefined → `isAdmin` 退回 false → 管理者會**短暫看到**「僅顯示您所開設的課程」。
    // 它會自我修正，但那句是裁示 C 的強制配套，閃現錯誤版本與顯示錯誤版本同樣不可接受。
    server.use(
      http.get("/api/et/courses/capabilities", () =>
        HttpResponse.json({ can_create_course: false, can_manage_courses: true, can_learn: false }),
      ),
      // 讓 module-summary 慢於 capabilities 回來
      http.get("/api/dp/user/module-summary", async () => {
        await new Promise((r) => setTimeout(r, 80))
        return HttpResponse.json({ et: { has_role: true, is_admin: true }, dm: { has_role: false, is_admin: false } })
      }),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    // capabilities 先回來的那個空窗期：不得已 isAdmin=false 渲染出教師視角
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
    expect(await screen.findByLabelText("學員姓名或 Email")).toBeInTheDocument()
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("兼具教師與學員角色時顯示教師視角", async () => {
    // 他自己的已通過課程在 ET04「我的課程」看得到；兩張表塞同一頁只會讓畫面變長。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByLabelText("學員姓名或 Email")).toBeInTheDocument()
  })
})
