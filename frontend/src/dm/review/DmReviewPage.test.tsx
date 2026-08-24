import { screen } from "@testing-library/react"
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
      HttpResponse.json([
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
        },
      ]),
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

describe("DmReviewPage 簽核中心（DM04）", () => {
  it("待簽核清單：列出指派項目、停留逾門檻標紅警示", async () => {
    renderWithProviders(<DmReviewPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    // 停留 12 天（≥ 7）→ 標紅 ⚠
    expect(screen.getByText(/12 天 ⚠/)).toBeInTheDocument()
    expect(screen.getByText(/1 天/)).toBeInTheDocument()
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

  it("核准並發布 → 二次確認 → 成功 toast（DM-MSG-DM04-001）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmReviewPage />)
    await user.click(await screen.findByText("領血確認標準作業程序"))
    await user.click(await screen.findByRole("button", { name: "核准並發布" }))
    // 二次確認 dialog
    expect(await screen.findByText("確定核准此項目？")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "確認核准" }))
    expect(await screen.findByText("已核准並發布，已通知撰寫者")).toBeInTheDocument()
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
