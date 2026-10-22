import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmPersonalPage } from "./DmPersonalPage"
import { navFrom } from "../../layouts/activeNav"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy }
})

beforeEach(() => navigateSpy.mockClear())

/** 與 `test/server.ts` 兩筆 resolved + REJECTED 事件的 `reason` 逐字相同（#554）。 */
const REJECT_REASON = "版本號格式不符，請改為 1.0，並補上變更摘要說明以利審核判斷是否影響既有流程"

/** 錯誤訊息用：印出該欄的原始寬度字串（空字串時 parseFloat 會是 NaN，看不出原值）。 */
function c0(cols: HTMLTableColElement[], j: number) {
  return cols[j].style.width || "(未設定)"
}

describe("DmPersonalPage 個人專區（DM04）", () => {
  it("我的文件動態：撰寫者 / 審核者視角事件；送審中可撤回；逾門檻顯催辦中（AC5）", async () => {
    renderWithProviders(<DmPersonalPage />)
    expect(await screen.findByText("待審文件 A")).toBeInTheDocument() // 撰寫者視角（送審中）
    expect(screen.getByText("我逾期要審的文件")).toBeInTheDocument() // 審核者視角
    expect(screen.getByText("撰寫者視角（近 30 天）")).toBeInTheDocument()
    expect(screen.getByText("審核者視角（近 30 天）")).toBeInTheDocument()
    // 送審中 → 有撤回送審鈕
    expect(screen.getByRole("button", { name: "撤回送審" })).toBeInTheDocument()
    // 審核者視角逾催辦門檻 → 顯示「催辦中」（is_overdue=true）
    expect(screen.getByText("催辦中")).toBeInTheDocument()
    // 待處理 / 催辦中 → 有「前往簽核中心」button
    expect(screen.getByRole("button", { name: "前往簽核中心" })).toBeInTheDocument()
    // 狀態變動歷程：同一送審週期展開為 送審 + 退回 兩列（#5）
    expect(screen.getAllByText("被退回文件 B")).toHaveLength(2)
    expect(screen.getAllByText("已退回").length).toBeGreaterThanOrEqual(1) // resolved 事件（撰寫者/審核者皆有）
    // 對造人欄（指定審核者 / 送審者）中文姓名
    expect(screen.getByText("送審者")).toBeInTheDocument() // 審核者視角表頭
    expect(screen.getAllByText("陳送審").length).toBeGreaterThanOrEqual(1)
    // 審核者視角已完成項也展開為兩列（Round-4 item 2）：送審 + 已退回
    expect(screen.getAllByText("我已退回的文件 D")).toHaveLength(2)
    // 標籤一律中文、不再出現「收到送審」
    expect(screen.queryByText("收到送審")).not.toBeInTheDocument()
  })

  it("撤回送審 → 二次確認 → 成功 toast（DM-MSG-DM04-005）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("button", { name: "撤回送審" }))
    expect(await screen.findByText("確定撤回送審？")).toBeInTheDocument()
    // 原本只斷言標題，**對話框內文零覆蓋**——那正是 PR #686 漏掉第 8 處的原因之一。
    // `SUBMIT_WITHDRAWN` 的 CHANNEL 為 `MSG` ⇒ 平台不推送任何通知，內文不得宣稱「並通知原指派審核者」。
    expect(screen.getByText("撤回後送審項目將回到草稿 / 已發布狀態。")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認撤回" }))
    expect(await screen.findByText("已撤回送審")).toBeInTheDocument()
  })

  it("草稿匣：三類標記 + 繼續編輯 / 刪除；已廢止孤兒草稿仍顯示但續編灰化", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    expect(await screen.findByText("領血 SOP 草稿")).toBeInTheDocument()
    expect(screen.getByText("被退回待修改")).toBeInTheDocument() // rejected 類
    expect(screen.getAllByText("未送審").length).toBeGreaterThanOrEqual(1) // unsubmitted 類
    // 已廢止孤兒草稿仍留在草稿匣（不隱藏）
    expect(screen.getByText("已廢止孤兒草稿")).toBeInTheDocument()
    // 三筆皆有「繼續編輯」；已廢止那筆為 disabled、其餘可按
    const editButtons = screen.getAllByRole("button", { name: "繼續編輯" })
    expect(editButtons).toHaveLength(3)
    expect(editButtons.filter((b) => (b as HTMLButtonElement).disabled)).toHaveLength(1)
    // 已廢止列可刪除（讓使用者自行清掉）
    expect(screen.getAllByRole("button", { name: "刪除" })).toHaveLength(3)
  })

  it("🔴 點「繼續編輯」→ 導向編輯模式，並帶來源讓側欄留在 DM04", async () => {
    // 編輯頁預設高亮 DM01 文件庫（它有三條入口、網址都一樣）；不帶來源的話，
    // 從個人專區的草稿按下去側欄會跳到 DM01。
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    const editButtons = await screen.findAllByRole("button", { name: "繼續編輯" })
    await user.click(editButtons.find((b) => !(b as HTMLButtonElement).disabled)!)
    expect(navigateSpy).toHaveBeenCalledWith(expect.stringMatching(/^\/dm\/documents\/.+\/edit$/), navFrom("/dm/me"))
  })

  it("草稿匣「分類」欄顯示中文名稱、不顯示代碼（#735）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    await screen.findByText("領血 SOP 草稿")

    // 正向：三筆草稿的分類各自以中文名稱呈現（fixture 為 SOP ×2、OTHER ×1）
    expect(screen.getAllByText("標準作業程序")).toHaveLength(2)
    expect(screen.getByText("其他")).toBeInTheDocument()

    // 反向：代碼不得單獨出現。⭐ 與正向用**同一個** `*ByText` 家族——否則「找不到」
    // 可能只是查詢方式對不上，而不是真的沒顯示（否定斷言最常見的假通過）。
    // 本頁分類有自己的 `<TableCell>`，所以字串完全比對有效；DM00 公告列是合併字串，
    // 同樣寫法在那裡會恆真，故該處改用正則（見 `DmOverviewWidget.test.tsx`）。
    expect(screen.queryByText("SOP")).not.toBeInTheDocument()
    expect(screen.queryByText("OTHER")).not.toBeInTheDocument()
  })

  it("草稿匣：父文件在廢止待簽核時「繼續編輯」一併灰化，並說明原因（#615）", async () => {
    // #615：PENDING_OBSOLETE 期間入口原本仍可點，使用者進編輯器填完按儲存才被 DM_DOC_008 擋，
    // 而 `update_draft_version` 在 409 前不寫入 ⇒ 當次編輯內容直接遺失。
    //
    // ⚠️ 用 server.use() 局部覆寫、**不改共用夾具**——上一條測試斷言「3 顆、1 顆 disabled」，
    // 動共用夾具會把它弄壞（而那與本 issue 無關）。
    server.use(
      http.get("/api/dm/personal/drafts", () =>
        HttpResponse.json([
          {
            version_id: 711,
            doc_id: "DM-SOP-000020",
            doc_name: "廢止簽核中的草稿",
            version_no: "3.0",
            change_summary: "編到一半對方發起廢止",
            category_code: "SOP",
            kind: "unsubmitted",
            updated_date: "2026-08-23T09:00:00Z",
            doc_status: "PENDING_OBSOLETE",
          },
        ]),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    // 正向錨點：該列確實渲染出來了（草稿不因廢止待簽核而消失）——
    // 否則下面「鈕是 disabled」會在「整列都沒渲染」時取不到元素而以別的理由失敗。
    expect(await screen.findByText("廢止簽核中的草稿")).toBeInTheDocument()

    const editButton = screen.getByRole("button", { name: "繼續編輯" })
    expect(editButton).toBeDisabled()

    // 「有原因」：hover 後 tooltip 說明為何暫時不能編，且**不是**已廢止那句（兩者原因不同）
    await user.hover(editButton.parentElement as HTMLElement)
    expect(await screen.findByText(/此文件正在廢止簽核中/)).toBeInTheDocument()
    expect(screen.queryByText(/此文件已被廢止/)).not.toBeInTheDocument()

    // 草稿本身仍可刪除（與已廢止列一致，讓使用者自行清掉）
    expect(screen.getByRole("button", { name: "刪除" })).toBeInTheDocument()
  })

  it("刪除草稿 → 確認（DM-MSG-DM04-004）→ 成功 toast", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmPersonalPage />)
    await user.click(await screen.findByRole("tab", { name: "草稿匣" }))
    await screen.findByText("領血 SOP 草稿")
    await user.click(screen.getAllByRole("button", { name: "刪除" })[0])
    expect(await screen.findByText("確定刪除此草稿？刪除後不可復原")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認刪除" }))
    expect(await screen.findByText("草稿已刪除")).toBeInTheDocument()
  })

  it("動態載入失敗 → 顯示錯誤", async () => {
    const { server } = await import("../../test/server")
    const { http, HttpResponse } = await import("msw")
    server.use(http.get("/api/dm/personal/activity", () => HttpResponse.json({ detail: "err" }, { status: 500 })))
    renderWithProviders(<DmPersonalPage />)
    expect(await screen.findByText(/載入動態失敗/)).toBeInTheDocument()
  })
  it("審核者帳號已停用時，撰寫者看得出原因並可據以撤回（#395 AC 4 選項 D）", async () => {
    // ⭐ 撰寫者本來就能撤回重送，缺的只是**沒有任何東西告訴他該撤回**——他看到的是
    // 「送審中」，卡 1 天和卡 100 天字樣完全相同，而審核者已經登不進系統了。
    const { server } = await import("../../test/server")
    const { http, HttpResponse } = await import("msw")
    server.use(
      http.get("/api/dm/personal/activity", () =>
        HttpResponse.json({
          author: [
            {
              review_id: 901,
              doc_id: "DM-SOP-000901",
              doc_name: "卡住的文件",
              review_type: "NEW",
              status: "PENDING",
              event_kind: "submitted",
              event_time: "2026-07-01T09:00:00Z",
              is_overdue: true,
              party_name: "李停用",
              party_unreachable: "DISABLED",
            },
          ],
          reviewer: [],
        }),
      ),
    )
    renderWithProviders(<DmPersonalPage />)

    expect(await screen.findByText("卡住的文件")).toBeInTheDocument()
    expect(screen.getByText(/審核者帳號已停用/)).toBeInTheDocument()
    // 知道之後要做得到：撤回鈕必須同時在
    expect(screen.getByRole("button", { name: "撤回送審" })).toBeInTheDocument()
  })

  it("查無審核者帳號與已停用顯示不同文字（#395 D-2）", async () => {
    // ⚠️ 兩類不可併成一句——補救動作不同（修資料 vs 換審核者），與催辦 log 的三分法同判準。
    const { server } = await import("../../test/server")
    const { http, HttpResponse } = await import("msw")
    server.use(
      http.get("/api/dm/personal/activity", () =>
        HttpResponse.json({
          author: [
            {
              review_id: 902,
              doc_id: "DM-SOP-000902",
              doc_name: "孤兒指派文件",
              review_type: "NEW",
              status: "PENDING",
              event_kind: "submitted",
              event_time: "2026-07-01T09:00:00Z",
              is_overdue: true,
              party_name: null,
              party_unreachable: "NOT_FOUND",
            },
          ],
          reviewer: [],
        }),
      ),
    )
    renderWithProviders(<DmPersonalPage />)

    expect(await screen.findByText(/查無審核者帳號/)).toBeInTheDocument()
    expect(screen.queryByText(/審核者帳號已停用/)).not.toBeInTheDocument()
  })

  it("撰寫者視角逾催辦門檻顯「逾期未審」，不再只說「送審中」（#395 D-2）", async () => {
    // 🔴 卡 1 天與卡 100 天原本字樣完全相同——`authorEventLabel` 根本不吃 `is_overdue`，
    // 而該欄位其實早就送到前端了。
    const { server } = await import("../../test/server")
    const { http, HttpResponse } = await import("msw")
    server.use(
      http.get("/api/dm/personal/activity", () =>
        HttpResponse.json({
          author: [
            {
              review_id: 903,
              doc_id: "DM-SOP-000903",
              doc_name: "等很久的文件",
              review_type: "NEW",
              status: "PENDING",
              event_kind: "submitted",
              event_time: "2026-07-01T09:00:00Z",
              is_overdue: true,
              party_name: "王審核",
              party_unreachable: null,
            },
          ],
          reviewer: [],
        }),
      ),
    )
    renderWithProviders(<DmPersonalPage />)

    expect(await screen.findByText("等很久的文件")).toBeInTheDocument()
    expect(screen.getByText("逾期未審")).toBeInTheDocument()
    expect(screen.queryByText("送審中")).not.toBeInTheDocument()
  })

  it("退回原因是「狀態」後的獨立欄位，不再需要展開（#554 讀取端、#657 改版面）", async () => {
    // #554：DOC_REJECT / OBS_REJECT 改站內後，那封「退回原因：{reason}」的信不再寄出，
    // 本頁成為 DM_REVIEW.REASON 唯一的讀取端——沒有這條測試，原因欄會靜默變成沒人看得到。
    // #657：原本是狀態欄內的展開鈕 + 展開列，改為正式欄位。
    renderWithProviders(<DmPersonalPage />)
    await screen.findByText("待審文件 A")

    // 表頭存在（正向錨點：證明下面的否定斷言有東西可對照）
    expect(screen.getAllByText("退回原因").length).toBeGreaterThanOrEqual(1)
    // 原因全文直接在欄位裡，不必點任何東西；撰寫者 / 審核者視角各一列
    expect(screen.getAllByText(REJECT_REASON)).toHaveLength(2)

    // #657：展開 / 收合的設計已移除——與上面的正向斷言用同一種查詢方式
    expect(screen.queryByRole("button", { name: "展開退回原因" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "收合退回原因" })).not.toBeInTheDocument()
  })

  it("廢止申請被退回時顯示審核者的退回原因（#679）", async () => {
    // #679 之前：`DM_REVIEW.REASON` 對 OBSOLETE 裝的是**申請人**寫的廢止申請原因，
    // 審核者的退回原因只進稽核與 OBS_REJECT 通知（而該通知自 #554 起是 MSG、
    // 系統沒有站內訊息畫面）⇒ 申請人在任何畫面都看不到自己為什麼被退回。
    renderWithProviders(<DmPersonalPage />)

    // 正向錨點：該列有渲染（否則下方斷言恆真）
    expect(await screen.findByText("申請廢止被退回的文件 E")).toBeInTheDocument()
    expect(screen.getByText("仍需沿用至年底，暫不廢止")).toBeInTheDocument()
  })

  it("colgroup 的欄寬數量必須等於表頭欄位數（#679 防重犯）", async () => {
    // 🔴 這條守的是 #657 造成的回歸：當時新增「退回原因」欄（6→7 欄），但 `ACTIVITY_COLS`
    // 仍只有 6 個值，第 7 欄「操作」分到的寬度為 0 ⇒ 撰寫者的「撤回送審」與審核者的
    // 「前往簽核中心」在正常畫面上看不到，使用者無從得知這兩個操作存在。
    //
    // ⚠️ 不驗「實際像素寬」：jsdom 不做排版，`offsetWidth` 一律是 0，驗了等於恆真。
    // 改驗**結構不變量**——`<col>` 數與 `<th>` 數必須相等。加欄時忘了補寬度就會紅，
    // 而那正是 #657 當時沒有任何東西在對帳的那一點。
    const { container } = renderWithProviders(<DmPersonalPage />)
    await screen.findByText("待審文件 A")

    const tables = container.querySelectorAll("table")
    expect(tables.length).toBeGreaterThan(0) // 正向錨點：表格有渲染出來
    tables.forEach((table, i) => {
      const cols = Array.from(table.querySelectorAll<HTMLTableColElement>("colgroup col"))
      const ths = table.querySelectorAll("thead th").length
      expect(ths).toBeGreaterThan(0)
      expect(cols.length, `第 ${i + 1} 個表格：colgroup ${cols.length} 個、表頭 ${ths} 欄，數量不符`).toBe(ths)

      // 數量相等還不夠：`["34%", …, "0%"]` 數量對、第 7 欄仍然不可見。inline style 在 jsdom
      // 會保留（不需排版引擎），所以每一欄的寬度值驗得到。
      const widths = cols.map((c) => parseFloat(c.style.width))
      widths.forEach((w, j) => {
        expect(w, `第 ${i + 1} 個表格第 ${j + 1} 欄寬度為 ${c0(cols, j)}`).toBeGreaterThan(0)
      })
      // 總和須為 100%，否則 fixed layout 下最後一欄會被擠壓或溢出
      expect(Math.round(widths.reduce((a, b) => a + b, 0))).toBe(100)
    })
  })

  it("草稿匣頁籤只對編輯者顯示（#657；spec_us9 FR-001）", async () => {
    // 建草稿的端點全掛 `_ensure_editor`，純審核者不可能有草稿 → 那個頁籤對他永遠是空的。
    server.use(http.get("/api/dm/personal/access", () => HttpResponse.json({ can_access: true, can_draft: false })))
    renderWithProviders(<DmPersonalPage />)
    await screen.findByText("待審文件 A")

    // 正向錨點：個人專區本身進得去（can_access 仍為 true），只是少了草稿匣那一個頁籤
    expect(screen.getByRole("tab", { name: "我的文件動態" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "草稿匣" })).not.toBeInTheDocument()
  })

  it("非編輯者以 ?tab=drafts 深連結進入時落在我的文件動態（#657）", async () => {
    // 深連結來自編輯器續編後導回。非編輯者不該停在空白頁或壞掉的頁籤狀態。
    server.use(http.get("/api/dm/personal/access", () => HttpResponse.json({ can_access: true, can_draft: false })))
    // 路徑用實際的 `/dm/me`（router.tsx 的 `path: "me"`，編輯器續編後導回的也是這個）——
    // `useSearchParams` 只看 query string，寫錯路徑測試照樣過，但會誤導讀者
    renderWithProviders(<DmPersonalPage />, undefined, ["/dm/me?tab=drafts"])

    expect(await screen.findByText("待審文件 A")).toBeInTheDocument() // 動態的內容
    expect(screen.queryByRole("tab", { name: "草稿匣" })).not.toBeInTheDocument()
  })

  it("編輯者以 ?tab=drafts 深連結進入時直接落在草稿匣（#657）", async () => {
    // 正向路徑：編輯器「儲存為草稿」後會 navigate 到 `/dm/me?tab=drafts`（DmEditorPage.test.tsx:395）。
    // 只測非編輯者 fallback 的話，把折回條件寫反（例如漏掉 `!canDraft`）不會有任何測試變紅。
    // 預設 fixture 的 can_draft 為 true，即編輯者情境。
    renderWithProviders(<DmPersonalPage />, undefined, ["/dm/me?tab=drafts"])

    // 直接看到草稿匣內容，不必點頁籤
    expect(await screen.findByText("領血 SOP 草稿")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "草稿匣" })).toBeInTheDocument()
  })

  it("同一送審週期的「送審」事件不帶退回原因（#554）", async () => {
    renderWithProviders(<DmPersonalPage />)
    await screen.findByText("待審文件 A")

    // 正向錨點：已退回週期的「送審」起點列確實有渲染（撰寫者 + 審核者各一）。
    // ⚠️ 這兩列的 status 同樣是 REJECTED——只看 status 不看 event_kind 的話，
    // 它們會被誤判成該顯示原因（後端 _build_events 正是以 event_kind 分流）。
    expect(screen.getAllByText("送審")).toHaveLength(2)
    // 3 ＝ 被退回文件 B 的撰寫者 / 審核者各一 + #679 新增的廢止退回列（撰寫者視角）。
    // ⚠️ 這個數字綁 fixture：動 `server.ts` 的 activity 列時要一起看，別只把它改成「跑出來的那個數」
    //——要先確認多出來的那列**該不該**存在。
    expect(screen.getAllByText("已退回")).toHaveLength(3)
    // 4 列 REJECTED 中只有 2 列（resolved）帶原因。
    //
    // ⚠️ 本條**守不住**「只看 status 不看 event_kind」那個缺陷：前端只是忠實渲染後端給的
    // `reason`，自己不判斷 event_kind，所以後端改錯了這裡也不會變 4。真正的守門在後端
    // `test_dm_personal_flow.py` 的 `submitted[0].reason is None`。
    // （原本數展開鈕的寫法有同一個弱點，#657 只是改了呈現方式，不是退步。）
    // 本條的價值是：確認前端把「有值 / 無值」如實反映到欄位上，沒有自行補值或吃掉。
    expect(screen.getAllByText(REJECT_REASON)).toHaveLength(2)
  })
})
