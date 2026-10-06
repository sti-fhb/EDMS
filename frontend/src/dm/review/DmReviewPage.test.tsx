import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { DmReviewPage } from "./DmReviewPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 覆寫待簽核清單 + 明細為一筆廢止類送審（US8）。 */
function useObsoleteReview() {
  server.use(
    http.get("/api/dm/reviews/pending", () =>
      HttpResponse.json({
      data: [
        {
          review_id: 601,
          doc_id: "DM-SOP-000009",
          doc_name: "待廢止 SOP",
          category_code: "SOP",
          review_type: "OBSOLETE",
          version_no: "1.5",
          submitter_id: "u1",
          submitter_name: "王曉明",
          submit_date: "2026-08-18T10:00:00Z",
          waiting_days: 2,
          overdue: false,
        },
      ],
      meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
    }),
    ),
    // completed 為單一路徑段，會被下方 :reviewId 覆寫攔截 → 需先明確保留（回空清單）
    http.get("/api/dm/reviews/completed", () =>
      HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
    ),
    http.get("/api/dm/reviews/:reviewId", ({ params }) =>
      HttpResponse.json({
        review_id: Number(params.reviewId),
        doc_id: "DM-SOP-000009",
        doc_name: "待廢止 SOP",
        category_code: "SOP",
        category_name: "標準作業程序",
        audience_tags: ["全單位 + 全體"],
        retrieval_tags: [],
        review_type: "OBSOLETE",
        change_summary: null,
        submit_date: "2026-08-18T10:00:00Z",
        submitter_id: "u1",
        submitter_name: "王曉明",
        new_version: {
          version_id: 15,
          version_no: "1.5",
          file_name: "SOP-1.5.pdf",
          file_size: 1800000,
          file_mime: "application/pdf",
          previewable: true,
        },
        current_version: null,
        obsolete_reason: "院內已停止實施此流程",
        obsolete_file_name: "停辦函文.pdf",
        obsolete_file_size: 600000,
      }),
    ),
  )
}

describe("DmReviewPage 簽核中心（DM02）", () => {
  it("待簽核清單：列出指派項目、標紅依後端 overdue 而非前端寫死門檻", async () => {
    renderWithProviders(<DmReviewPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()

    // fixture 的這筆只停留 **4 天**（低於舊的寫死值 7）卻 overdue=true——管理者把門檻調成 3 的情境。
    // 前端若退回自己比對 7，這裡就不會有 ⚠（#503 第 1 項）。
    expect(screen.getByText(/4 天 ⚠/)).toBeInTheDocument()
    // 對照：overdue=false 的那筆不得有 ⚠
    expect(screen.getByText(/^1 天$/)).toBeInTheDocument()
  })

  it("點列展開明細：版本對照表（狀態 pill + 下載）+ 核准/退回 + X 收合", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    expect(await screen.findByText(/簽核明細 —/)).toBeInTheDocument()
    expect(screen.getByText(/補充第 5 點異常通報流程/)).toBeInTheDocument()
    // 版本對照表：目前發布版 + 待審新版 狀態 pill
    expect(screen.getByText("待審新版")).toBeInTheDocument()
    expect(screen.getByText("目前發布版")).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /下載/ }).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole("button", { name: "核准並發布" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "退回" })).toBeInTheDocument()
    // X 收合明細面板
    await user.click(screen.getByRole("button", { name: "收合" }))
    expect(screen.queryByText(/簽核明細 —/)).not.toBeInTheDocument()
  })

  it("明細顯示本次送審之可見對象 / 檢索標籤；分類不重複顯示（#377、#437）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await screen.findByText(/簽核明細 —/)

    expect(screen.getByText("可見對象")).toBeInTheDocument()
    expect(screen.getByText("檢索標籤")).toBeInTheDocument()
    // 可見對象以「單位 + 職位」成對呈現（#437）——審核者要核對的是「哪種人看得到」，
    // 兩端拆開後多組配對無從對應，故此處刻意斷言整組字串而非兩端各自存在
    expect(screen.getByText("全單位 + 全體")).toBeInTheDocument()
    expect(screen.getByText("國防部軍醫局 + 護理師")).toBeInTheDocument()
    expect(screen.getByText("採血")).toBeInTheDocument()
    // 分類只在清單各列出現（mock 兩列皆 SOP），明細不再重複顯示 → 恰為 2 個、且為中文名
    expect(screen.getAllByText("標準作業程序")).toHaveLength(2)
    expect(screen.queryByText("SOP")).not.toBeInTheDocument()
  })

  it("深連結 ?reviewId= 自動展開該筆簽核明細（個人專區前往簽核中心）", async () => {
    renderWithProviders(<DmReviewPage />, undefined, ["/dm/review?reviewId=502"])
    // 未點任何列，明細面板即自動展開
    expect(await screen.findByText(/簽核明細 —/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "核准並發布" })).toBeInTheDocument()
  })

  it("核准並發布 → 二次確認 → 成功 toast（DM-MSG-DM02-001）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    // 二次確認 dialog
    expect(await screen.findByText("確定核准此項目？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認核准" }))
    expect(await screen.findByText("已核准並發布，已通知撰寫者")).toBeInTheDocument()
  }, 20000)

  it("撰寫者已撤回 → 顯示 DM-MSG-DM02-006、明細收起、該列自清單消失", async () => {
    const user = userEvent.setup({ delay: null })
    // 核准回 409 DM_REVIEW_009；同時讓重新查詢的清單不再含那一筆（＝伺服器端已撤回）
    server.use(
      http.post("/api/dm/reviews/501/approve", () =>
        HttpResponse.json({ error_code: "DM_REVIEW_009", error_message: "此項目已被撰寫者撤回" }, { status: 409 }),
      ),
    )
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    await user.click(await screen.findByRole("button", { name: "確認核准" }))

    expect(await screen.findByText("此項目已被撰寫者撤回，已自清單移除")).toBeInTheDocument()
    // 「已自清單移除」在實作上＝重新查詢 + 收起明細。此前只有成功才刷新，明細會一直開著（#503 第 2 項）
    await waitFor(() => expect(screen.queryByText(/簽核明細 —/)).not.toBeInTheDocument())
  }, 20000)

  it("其他終態（已處理過）維持原訊息，不誤報為撤回", async () => {
    const user = userEvent.setup({ delay: null })
    server.use(
      http.post("/api/dm/reviews/501/approve", () =>
        HttpResponse.json(
          { error_code: "DM_REVIEW_003", error_message: "此送審已非待審核狀態，無法處理" },
          { status: 409 },
        ),
      ),
    )
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    await user.click(await screen.findByRole("button", { name: "確認核准" }))

    expect(await screen.findByText("此送審已非待審核狀態，無法處理")).toBeInTheDocument()
    expect(screen.queryByText("此項目已被撰寫者撤回，已自清單移除")).not.toBeInTheDocument()
  }, 20000)

  it("退回：空原因擋（-004）、填原因後成功 toast（-005）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "退回" }))
    // 空原因 → 擋
    await user.click(await screen.findByRole("button", { name: "確認退回" }))
    expect(await screen.findByText("請填寫退回原因")).toBeInTheDocument()
    // 填原因 → 成功
    await user.type(screen.getByLabelText(/退回原因/), "需補充異常通報")
    await user.click(screen.getByRole("button", { name: "確認退回" }))
    expect(await screen.findByText("已退回並通知撰寫者")).toBeInTheDocument()
  }, 20000)

  it("廢止類明細：廢止原因 + 廢止對象 + 附件下載 + 「核准並廢止」（US8）", async () => {
    const user = userEvent.setup({ delay: null })
    useObsoleteReview()
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("待廢止 SOP"))
    expect(await screen.findByText("院內已停止實施此流程")).toBeInTheDocument() // 廢止原因（變更摘要欄位）
    expect(screen.getByText("廢止檔案")).toBeInTheDocument() // 檔案區標題（與新增/新版本一致命名）
    expect(screen.getByText("廢止待簽核")).toBeInTheDocument() // 狀態 pill
    expect(screen.getByRole("button", { name: "下載廢止附件" })).toBeInTheDocument() // 附件下載（不重複檔名）
    expect(screen.getByRole("button", { name: "核准並廢止" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "核准並發布" })).not.toBeInTheDocument()
  })

  it("核准並廢止 → 二次確認 → 成功 toast（US8）", async () => {
    const user = userEvent.setup({ delay: null })
    useObsoleteReview()
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("待廢止 SOP"))
    await user.click(await screen.findByRole("button", { name: "核准並廢止" }))
    expect(await screen.findByText("確定核准廢止此文件？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認廢止" }))
    expect(await screen.findByText("已核准廢止，文件已下架並通知撰寫者")).toBeInTheDocument()
  }, 20000)

  it("處理完當頁最後一筆後不會停在空白頁，也不會謊稱沒有待簽核項目", async () => {
    // 共 21 筆 → 第 2 頁僅 1 筆。核准它之後 total 變 20、第 2 頁不復存在，後端回空 data。
    // 修正前：畫面顯示「目前沒有待簽核項目。」而頁籤寫「待簽核（20）」，且分頁列隨該分支一起
    // 消失 → 使用者沒有任何入口回第 1 頁（#503 code review MEDIUM-2 / security M-1）。
    let processed = false
    server.use(
      http.get("/api/dm/reviews/pending", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1)
        const total = processed ? 20 : 21
        const totalPages = Math.ceil(total / 20)
        const onThisPage = page > totalPages ? 0 : page === 1 ? 20 : total - 20
        return HttpResponse.json({
          data: Array.from({ length: onThisPage }, (_, i) => ({
            review_id: 900 + (page - 1) * 20 + i,
            doc_id: `DM-SOP-0009${String(i).padStart(2, "0")}`,
            doc_name: `第 ${page} 頁第 ${i + 1} 筆`,
            category_code: "SOP",
            category_name: "標準作業程序",
            review_type: "NEW",
            version_no: "1.0",
            submitter_id: "u1",
            submitter_name: "送審者",
            submit_date: "2026-08-18T10:00:00Z",
            waiting_days: 1,
            overdue: false,
          })),
          meta: { total, page, limit: 20, total_pages: totalPages },
        })
      }),
      http.post("/api/dm/reviews/:reviewId/approve", () => {
        processed = true
        return HttpResponse.json({ published_version_id: 1, notified: 0 })
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await screen.findByText("第 1 頁第 1 筆")

    await user.click(screen.getByRole("button", { name: "Go to page 2" }))
    await user.click(await screen.findByText("第 2 頁第 1 筆"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    await user.click(await screen.findByRole("button", { name: "確認核准" }))

    // 夾回第 1 頁並顯示內容；不得出現「沒有待簽核項目」的假空狀態
    await waitFor(() => expect(screen.getByText("第 1 頁第 1 筆")).toBeInTheDocument())
    expect(screen.queryByText("目前沒有待簽核項目。")).not.toBeInTheDocument()
  }, 20000)

  it("安全網：清單縮短幅度大於自己處理的那筆時，給真實訊息並保留分頁列", async () => {
    // 退頁邏輯只在「當頁剩最後一筆」時觸發。若清單同時因其他原因縮短（撰寫者一次撤回多筆），
    // 仍可能落在越界頁。此時畫面不得說「目前沒有待簽核項目。」——頁籤同時寫著「待簽核（20）」——
    // 且分頁列必須留著，否則使用者沒有入口回前一頁（#503 security review M-1）。
    let total = 22 // 第 1 頁 20 筆、第 2 頁 2 筆
    server.use(
      http.get("/api/dm/reviews/pending", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1)
        const totalPages = Math.ceil(total / 20)
        const onThisPage = page > totalPages ? 0 : page === 1 ? Math.min(20, total) : total - 20
        return HttpResponse.json({
          data: Array.from({ length: onThisPage }, (_, i) => ({
            review_id: 950 + (page - 1) * 20 + i,
            doc_id: `DM-SOP-0009${String(i).padStart(2, "0")}`,
            doc_name: `第 ${page} 頁第 ${i + 1} 筆`,
            category_code: "SOP",
            category_name: "標準作業程序",
            review_type: "NEW",
            version_no: "1.0",
            submitter_id: "u1",
            submitter_name: "送審者",
            submit_date: "2026-08-18T10:00:00Z",
            waiting_days: 1,
            overdue: false,
          })),
          meta: { total, page, limit: 20, total_pages: totalPages },
        })
      }),
      // 核准我這一筆的同時，撰寫者也撤回了另一筆 → 總數少 2，第 2 頁整個消失
      http.post("/api/dm/reviews/:reviewId/approve", () => {
        total = 20
        return HttpResponse.json({ published_version_id: 1, notified: 0 })
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await screen.findByText("第 1 頁第 1 筆")
    await user.click(screen.getByRole("button", { name: "Go to page 2" }))
    await screen.findByText("第 2 頁第 1 筆")

    // 當頁有 2 筆 → 退頁邏輯（只在剩 1 筆時）不觸發，必定落在越界頁
    await user.click(screen.getByText("第 2 頁第 1 筆"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    await user.click(await screen.findByRole("button", { name: "確認核准" }))

    expect(await screen.findByText("此頁已無待簽核項目，請返回前一頁。")).toBeInTheDocument()
    expect(screen.queryByText("目前沒有待簽核項目。")).not.toBeInTheDocument()
    // 斷言分頁列本身還在（不綁 MUI 在越界狀態下的個別頁碼 aria-label）——
    // 「使用者有入口回前一頁」正是這條要守的東西。
    // ⚠️ 用 findByRole 而非 getByRole：核准確認框關閉的過渡期間，MUI Dialog 會把背景設為
    // aria-hidden，而 role 查詢預設會過濾掉 aria-hidden 的元素（getByText 不會，所以上面
    // 那條 Alert 斷言先過了）。同步查詢會在那個瞬間落空。
    expect(await screen.findByRole("navigation")).toBeInTheDocument()
  }, 20000)

  it("已完成頁籤：呈現過往處理結果（唯讀）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByRole("tab", { name: /已完成/ }))
    expect(await screen.findByText("舊案 SOP")).toBeInTheDocument()
    expect(screen.getByText("已核准")).toBeInTheDocument()
    // AC8 搜尋分頁：提供文件名搜尋框
    expect(screen.getByLabelText(/搜尋文件名稱/)).toBeInTheDocument()
  })
})

describe("DmReviewPage 日期欄（#539）", () => {
  const pendingAt = (submit_date: string) =>
    http.get("/api/dm/reviews/pending", () =>
      HttpResponse.json({
        data: [
          {
            review_id: 501,
            doc_id: "DM-SOP-000001",
            doc_name: "領血確認標準作業程序",
            category_code: "SOP",
            category_name: "標準作業程序",
            review_type: "NEW",
            version_no: "1.0",
            submitter_id: "u1",
            submitter_name: "陳大華",
            submit_date,
            waiting_days: 0,
            overdue: false,
          },
        ],
        meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
      }),
    )

  it("送審時間以台灣時間呈現：UTC 前一天 17:30 顯示為台灣隔日", async () => {
    server.use(pendingAt("2026-10-05T17:30:00Z"))
    renderWithProviders(<DmReviewPage />)
    expect(await screen.findByText("2026-10-06")).toBeInTheDocument()
    expect(screen.queryByText("2026-10-05")).not.toBeInTheDocument()
  })

  it("完成時間以台灣時間呈現：UTC 前一天 17:30 顯示為台灣隔日", async () => {
    const user = userEvent.setup()
    server.use(
      pendingAt("2026-08-01T04:00:00Z"),
      http.get("/api/dm/reviews/completed", () =>
        HttpResponse.json({
          data: [
            {
              review_id: 400,
              doc_id: "DM-SOP-000009",
              doc_name: "舊案 SOP",
              review_type: "NEW",
              status: "APPROVED",
              version_no: "1.0",
              complete_date: "2026-10-05T17:30:00Z",
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByRole("tab", { name: /已完成/ }))
    expect(await screen.findByText("2026-10-06")).toBeInTheDocument()
    expect(screen.queryByText("2026-10-05")).not.toBeInTheDocument()
  })
})
