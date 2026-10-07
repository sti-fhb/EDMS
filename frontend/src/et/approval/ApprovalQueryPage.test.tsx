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
        // #463 新增。本頁**刻意不掛任何 capability 旗標**（兩種角色都要進得去，見
        // `schemas.ts` 的說明），故此欄位不影響本檔任何斷言——補上只為 fixture 與
        // 真實回應同形，免得日後有人加旗標時拿到 `undefined` 而非 `false`。
        can_track_students: role === "teacher",
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

describe("ET04 核可查詢：教師 / 管理者視角", () => {
  it("輸入姓名查詢後列出核可紀錄，含課程、結果、核可人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")

    // fixture 三列同屬林佳蓉，故鎖定其中一列而非全頁比對
    const row = (await screen.findByText("採血作業新進人員訓練")).closest("tr")!
    expect(within(row).getByText("林佳蓉")).toBeInTheDocument()
    expect(within(row).getByText("王主任")).toBeInTheDocument()
    expect(within(row).getByText("通過")).toBeInTheDocument()
  })

  it("不需線下核可的通過列：核可人顯示「—」，不是空白（#464）", async () => {
    // 不需核可的課程**事實上沒有核可者**。留空白格會被讀成「核可人忘了填」或「資料沒載到」。
    asRole("teacher")
    server.use(
      http.post("/api/et/approvals/search", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "s_auto",
              user_name: "陳自學",
              course_id: 21,
              course_name: "線上自學課程",
              result: "PASS",
              result_note: null,
              approved_at: "2026-09-30T02:00:00Z",
              approved_by_name: null,
              is_revoked: false,
              revoke_reason: null,
              revoked_by_name: null,
              revoked_at: null,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "陳")

    const row = (await screen.findByText("線上自學課程")).closest("tr")!
    // 兩種通過畫面上不區分（#464 裁示）——結果欄一律是「通過」
    expect(within(row).getByText("通過")).toBeInTheDocument()
    expect(within(row).getByText("—")).toBeInTheDocument()
  })

  it("通過時間為空時顯示「—」（活化前就已完課的既有資料，#464）", async () => {
    // ⚠️ 本條驗的是**結果**（兩格都是「—」）。通過時間那格的「—」來自 `formatDateTime(null)`
    // 本身，核可人那格的「—」來自元件的 `?? "—"`——兩者來源不同。2026-09-30 變異檢查實測：
    // 拿掉元件對通過時間的額外判斷，本條照樣綠（因為那段判斷本來就是多餘的，已移除）。
    asRole("teacher")
    server.use(
      http.post("/api/et/approvals/search", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "s_old",
              user_name: "舊資料",
              course_id: 22,
              course_name: "既有完課課程",
              result: "PASS",
              result_note: null,
              approved_at: null,
              approved_by_name: null,
              is_revoked: false,
              revoke_reason: null,
              revoked_by_name: null,
              revoked_at: null,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "舊")

    const row = (await screen.findByText("既有完課課程")).closest("tr")!
    // 通過時間與核可人兩格都是「—」
    expect(within(row).getAllByText("—")).toHaveLength(2)
  })

  it("欄名為「通過時間」而非「核可時間」（#464）", async () => {
    // 不需核可的課程以完課時間計，那個時間不是任何人「核可」的時間。
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")

    expect(await screen.findByRole("columnheader", { name: "通過時間" })).toBeInTheDocument()
    // ⚠️ 正向對照組在上一行——同一個查詢方式（`columnheader` + name）確認找得到，
    // 下面這條「不存在」才有意義，不會因為查詢方式失效而恆真。
    expect(screen.queryByRole("columnheader", { name: "核可時間" })).not.toBeInTheDocument()
  })

  it("已撤銷的紀錄標示已撤銷並列出原因與撤銷人", async () => {
    asRole("teacher")
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "林")

    const row = (await screen.findByText("血品安全與品保概論")).closest("tr")!
    expect(within(row).getByText("已撤銷")).toBeInTheDocument()
    expect(within(row).getByText(/核可對象誤植/)).toBeInTheDocument()
    expect(within(row).getByText(/李管理員/)).toBeInTheDocument()
  })

  it("🔴 教師不得再看到任何可見範圍提示——裁示 C 已被推翻", async () => {
    // ↔️ 原本斷言「必須常駐顯示『不通過與已撤銷…僅顯示您所開設的課程』」，那是裁示 C
    // 的強制配套。#548 裁示 1 統一可見範圍後，那句話**變成錯的**：教師看得到的與管理者
    // 完全相同，留著它會讓人以為自己漏看了什麼。
    //
    // ⚠️ 本條是「不該出現」的斷言，所以**必須配一個正向錨點**（下一行的 findByLabelText）
    // 證明畫面真的渲染出來了——否則元件整個壞掉、什麼都沒有時它也會通過。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名或 Email")
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
    expect(screen.queryByText(/考核備註/)).not.toBeInTheDocument()
  })

  it("查無資料顯示空狀態提示（ET-MSG-ET04-001）", async () => {
    asRole("teacher")
    server.use(http.post("/api/et/approvals/search", () => HttpResponse.json(EMPTY)))
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "查無此人")

    expect(await screen.findByText(/查無符合條件的紀錄/)).toBeInTheDocument()
    // ↔️ 原本還斷言教師會看到「可能是該紀錄不在您的可見範圍內——請洽管理者查詢」。
    // 可見範圍統一後那句不再成立，說它會把人引去做一件沒有用的事。
    expect(screen.queryByText(/可能是該紀錄不在您的可見範圍內/)).not.toBeInTheDocument()
  })

  it("管理者的空狀態不提可見範圍（他沒有範圍限制，那句話對他是錯的）（#436）", async () => {
    // ⚠️ 反向斷言。對管理者說「可能不在您的可見範圍內」會讓他去找一個不存在的原因
    // ——他的 `visible_clause` 是 `true()`，查不到就是真的沒有。
    asRole("admin")
    server.use(http.post("/api/et/approvals/search", () => HttpResponse.json(EMPTY)))
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "查無此人")

    expect(await screen.findByText(/查無符合條件的紀錄/)).toBeInTheDocument()
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

    await waitFor(() => expect(seen.body?.keyword).toBe("林佳蓉"))
    expect(seen.url).not.toContain("林佳蓉")
    expect(seen.url).not.toContain("keyword")
    // 連編碼過的形式也不行——`encodeURIComponent` 後是看不出來的百分號序列
    expect(seen.url).not.toContain(encodeURIComponent("林佳蓉"))
  })

  /**
   * 🔴 這條守的是 #439（原 SA Q2 裁示 A）的「至少給一個條件」，**不是那顆按鈕**。
   *
   * #468 拿掉搜尋按鈕、改為輸入即查之後，原本的建構路徑（按下查詢）消失了——但它要驗
   * 的規則一個字都沒變。故改寫觸發方式、保留兩半斷言：
   *
   * | 斷言 | 擋的是 |
   * |---|---|
   * | `called === false` | 送了不該送的（後端會回 422 `ET_APPROVAL_006`，但前端不該去撞） |
   * | 提示文字仍在 | 使用者不知道為什麼沒有結果 |
   *
   * ⛔ 刪掉任何一半，那件事從此沒有測試。
   */
  it("🔴 已撤銷的列在核可結果欄不得顯示綠色「通過」（#548 裁示 6）", async () => {
    // 撤銷只設 `IS_REVOKED`，`RESULT` 仍是 `PASS`。改制前這一格只看 `result`，於是
    // 一筆已撤銷的通過在「核可結果」欄是綠色的「通過」，只有最右的「狀態」欄才寫
    // 已撤銷——整列雖有淡化，一眼掃過去讀到的就是通過。
    asRole("teacher")
    server.use(
      http.post("/api/et/approvals/search", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "s_rv",
              user_name: "林撤銷",
              course_id: 31,
              course_name: "已撤銷的課",
              result: "PASS",
              result_note: null,
              approved_at: "2026-09-30T02:00:00Z",
              approved_by_name: "王主任",
              is_revoked: true,
              revoke_reason: "核可對象誤植",
              revoked_by_name: "李管理員",
              revoked_at: "2026-10-01T02:00:00Z",
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    const row = (await screen.findByText("已撤銷的課")).closest("tr")!
    // 🔴 **「不該出現」配一個用同一查詢方式的「該出現」**——少了正向那半，整列沒渲染
    // 出來時這條也會通過。
    expect(within(row).getByText("已撤銷（原通過）")).toBeInTheDocument()
    expect(within(row).queryByText("通過")).not.toBeInTheDocument()
  })

  it("結果篩選的四態各自送出正確的參數對（#548 裁示 6）", async () => {
    // ⛔ 釘住「`result` 與 `revoked` 是兩個參數」。把它們壓成一個正是改制前那個缺陷的
    // 成因：「僅通過」只送 `result=PASS`、沒有撤銷條件，於是列出已撤銷的通過。
    asRole("teacher")
    const bodies: { result?: string; revoked?: boolean }[] = []
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        bodies.push((await request.json()) as { result?: string; revoked?: boolean })
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名或 Email")
    await waitFor(() => expect(bodies.length).toBe(1))

    for (const label of ["僅通過", "僅不通過", "僅已撤銷"]) {
      const before = bodies.length
      await user.click(screen.getByLabelText("核可結果"))
      await user.click(await screen.findByRole("option", { name: label }))
      // ⚠️ 必須等**長度增加**而不是 `at(-1)` 有值——後者在第一次之後恆為 true，
      // 等於沒等，而下一圈的點擊會在前一次請求還沒送出時就發生。
      await waitFor(() => expect(bodies.length).toBeGreaterThan(before))
    }

    // 初次載入的「全部結果」在最前。
    // ⚠️ 不可用 `toMatchObject({ result: undefined })`——JSON 序列化會把值為 undefined
    // 的鍵整個丟掉，而 `toMatchObject` 要求鍵存在，於是那樣寫必定失敗（且看起來像
    // 實作錯了）。「不篩」的正確表徵就是**鍵不存在**。
    expect(bodies[0].result).toBeUndefined()
    expect(bodies[0].revoked).toBeUndefined()
    expect(bodies.some((b) => b.result === "PASS" && b.revoked === false)).toBe(true)
    expect(bodies.some((b) => b.result === "FAIL" && b.revoked === false)).toBe(true)
    expect(bodies.some((b) => b.result === undefined && b.revoked === true)).toBe(true)
  })

  it("↔️ 不給任何條件也會送出請求並列出全部（#548 裁示 3）", async () => {
    // 原本這裡斷言「不送出」，空白畫面顯示「輸入學員姓名或 Email，或選擇課程即可查詢。」
    //
    // 那道閘（#468）擋的不是能力而是「不小心看到全院名單」，但它與使用者的需求直接
    // 衝突——「全部課程」與「全部結果」都是**不篩這個維度**的意思，兩者都是下拉預設值，
    // 分不出「刻意選了不篩」與「沒動過」。而它的理由（無法偵測誤用）已由裁示 5 的
    // 讀取稽核補上：不指名的查詢會寫 `DP_AUDIT_LOG`（`ACTION_TYPE=QUERY`）。
    asRole("teacher")
    let called = false
    server.use(
      http.post("/api/et/approvals/search", () => {
        called = true
        return HttpResponse.json(EMPTY)
      }),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名或 Email")
    await waitFor(() => expect(called).toBe(true))
    expect(screen.queryByText("輸入學員姓名或 Email，或選擇課程即可查詢。")).not.toBeInTheDocument()
  })

  /**
   * 🔴 `"   "` 等同未填——這條擋的是「去抖動後把原字串直接送出去」。
   *
   * 少了 `.trim()`，空白字串會被當成有效關鍵字，前端每打一個空格就發一次**必定 422**
   * 的請求，而畫面上只會看到結果沒出來，沒有任何東西會紅。
   */
  it("只打空白仍視為未給關鍵字——送出的 keyword 必須是 undefined", async () => {
    asRole("teacher")
    let called = false
    // ⚠️ 用物件包起來而不是裸 `let`：TS 看不穿 callback 內的賦值，會把 `lastBody`
    // 收斂成 `never`，於是 `lastBody?.keyword` 在 `tsc -b` 下報 TS2339。
    // 🔴 `pnpm tsc --noEmit` **不含測試檔**，只有 CI 用的 `tsc -b` 抓得到。
    const captured: { body?: { keyword?: string } } = {}
    server.use(
      http.post("/api/et/approvals/search", async ({ request }) => {
        called = true
        captured.body = (await request.json()) as { keyword?: string }
        return HttpResponse.json(EMPTY)
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<EtApprovalQueryPage />)

    await user.type(await screen.findByLabelText("學員姓名或 Email"), "   ")

    // 等超過去抖動（350ms）才斷言——太早問等於還沒到送出的時機，那是假綠
    await new Promise((r) => setTimeout(r, 600))
    // ↔️ 原本斷言 `called === false`。裁示 3 之後留白本來就會查，所以「有沒有送出」
    // 已經分不出 trim 有沒有做。改為斷言**送出的內容**：`keyword` 必須是 undefined
    // 而不是 `"   "`——後者會讓後端的比對變成 `%   %`，一筆都命中不到而畫面顯示查無。
    expect(called).toBe(true)
    expect(captured.body?.keyword).toBeUndefined()
  })

  it("查詢前不顯示空狀態——那會讓人以為已經查過且查無資料", async () => {
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByLabelText("學員姓名或 Email")
    // ⚠️ **必須用正則**，與正向對照組（`findByText(/查無符合條件的紀錄/)`）同一個查詢方式。
    // 畫面上實際是「查無符合條件的紀錄。」＋可見範圍提示，精確比對**永遠比對不到**——本條
    // 原本寫成 `queryByText("查無符合條件的紀錄")`，自 #436 加上句號起即恆真，直到 #464 的
    // 變異檢查才被發現。
    expect(screen.queryByText(/查無符合條件的紀錄/)).not.toBeInTheDocument()
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

    // ⚠️ 必須在**同一個** `waitFor` 裡等到兩者都在（#468）：改為輸入即查之後，姓名走
    // 去抖動而課程是即時的，「先打字、再選課」會先送出一次**只有課程**的請求。分開
    // 斷言的話第一句在那次請求就通過了，第二句拿到的仍是那一次的 body，於是恆紅。
    await waitFor(() => {
      expect(seen.body?.course_id).toBe(11)
      expect(seen.body?.keyword).toBe("林佳蓉")
    })
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

  it("🔴 課程清單載入失敗時說「載入失敗」，**不得**說「尚無通過紀錄」（#439）", async () => {
    // 後者是一句**假話**，而且比缺陷本身更糟——教師會據此以為系統裡真的沒有核可紀錄，
    // 而不是「剛才沒載到，重整一下」。ET02 的課程下拉踩過同一個坑（#390 的回歸）。
    asRole("teacher")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json({}, { status: 500 })))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("課程清單載入失敗，請重新整理後再試")).toBeInTheDocument()
    expect(screen.queryByText(/尚無通過紀錄/)).not.toBeInTheDocument()
  })

  it("沒有任何可選課程時說明原因，而不是給一個打得開卻空的下拉（#439）", async () => {
    asRole("teacher")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json([])))
    renderWithProviders(<EtApprovalQueryPage />)

    // ↔️ 原本是「您開設的課程尚無通過紀錄」。下拉不分 owner 之後（裁示 4），
    // 對教師與管理者都只剩「系統中尚無通過紀錄」這一種成因。
    expect(await screen.findByText("系統中尚無通過紀錄")).toBeInTheDocument()
  })

  it("管理者的空下拉不提「您開設的課程」——他沒有自己的課，那句話對他是錯的（#439）", async () => {
    // 與 #436 的空狀態同一條理由：對管理者說一個不適用於他的原因，會讓他去找一個
    // 不存在的問題。
    asRole("admin")
    server.use(http.get("/api/et/approvals/filter-courses", () => HttpResponse.json([])))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("系統中尚無通過紀錄")).toBeInTheDocument()
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

    expect(await screen.findByText("操作過於頻繁，請稍後再試")).toBeInTheDocument()
    // ⚠️ **必須用正則**，與正向對照組（`findByText(/查無符合條件的紀錄/)`）同一個查詢方式。
    // 畫面上實際是「查無符合條件的紀錄。」＋可見範圍提示，精確比對**永遠比對不到**——本條
    // 原本寫成 `queryByText("查無符合條件的紀錄")`，自 #436 加上句號起即恆真，直到 #464 的
    // 變異檢查才被發現。
    expect(screen.queryByText(/查無符合條件的紀錄/)).not.toBeInTheDocument()
  })
})

describe("ET04 核可查詢：學員視角", () => {
  it("學員側：不需核可課程的通過也列出，通過時間為空時顯示「—」（#464）", async () => {
    asRole("student")
    server.use(
      http.get("/api/et/approvals/mine", () =>
        HttpResponse.json({
          data: [{ course_id: 31, course_name: "我的自學課", approved_at: null }],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    const row = (await screen.findByText("我的自學課")).closest("tr")!
    expect(within(row).getByText("已通過")).toBeInTheDocument()
    expect(within(row).getByText("—")).toBeInTheDocument()
  })

  it("🔴 載入失敗顯示錯誤，**不得**渲染成「尚無已通過的課程」", async () => {
    asRole("student")
    server.use(
      http.get("/api/et/approvals/mine", () =>
        HttpResponse.json({ error_code: "COMMON_500", error_message: "系統發生錯誤" }, { status: 500 }),
      ),
    )
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("系統發生錯誤")).toBeInTheDocument()
    expect(screen.queryByText("您目前尚無已通過的課程")).not.toBeInTheDocument()
  })

  it("僅顯示自己已通過的課程，且不出現查詢框", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    // ⚠️ 用 regex 而非字串：欄位標籤是「學員姓名或 Email」，以 `"學員姓名"` 精確比對
    // **永遠找不到**——這條斷言在 #468 改到它之前是恆真的假證據。
    //
    // 原本還有一條「沒有查詢按鈕」，#468 拿掉按鈕後那條對誰都成立、分不出學員與教師，
    // 故移除而非留著（留著會看起來像有兩道防線）。
    expect(screen.queryByLabelText(/學員姓名/)).not.toBeInTheDocument()
  })

  it("不顯示教師視角的範圍提示", async () => {
    asRole("student")
    renderWithProviders(<EtApprovalQueryPage />)

    await screen.findByText("採血作業新進人員訓練")
    expect(screen.queryByText(/僅顯示您所開設的課程/)).not.toBeInTheDocument()
  })

  it("無已通過課程時顯示空狀態（ET-MSG-ET04-002）", async () => {
    asRole("student")
    server.use(http.get("/api/et/approvals/mine", () => HttpResponse.json(EMPTY)))
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByText("您目前尚無已通過的課程")).toBeInTheDocument()
  })
})

describe("ET04 核可查詢：共通", () => {
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
        HttpResponse.json({
          can_create_course: false,
          can_manage_courses: true,
          can_track_students: false,
          can_learn: false,
        }),
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
    // 他自己的已通過課程在 ET03「我的課程」看得到；兩張表塞同一頁只會讓畫面變長。
    asRole("teacher")
    renderWithProviders(<EtApprovalQueryPage />)

    expect(await screen.findByLabelText("學員姓名或 Email")).toBeInTheDocument()
  })
})
