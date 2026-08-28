import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { DmDetailPage } from "./DmDetailPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigateSpy, useParams: () => ({ docId: "DM-SOP-000001" }) }
})

describe("DmDetailPage 文件詳細頁", () => {
  it("標題列（識別+狀態）+ 資訊面板（描述性 metadata）+ 檔案區（PDF 可預覽+下載）", async () => {
    renderWithProviders(<DmDetailPage />)
    expect(await screen.findByText("領血確認標準作業程序")).toBeInTheDocument()
    expect(screen.getByText("DOC_ID: DM-SOP-000001")).toBeInTheDocument()
    // 資訊面板
    expect(screen.getByText("陳大華")).toBeInTheDocument()
    expect(screen.getByText("李主任")).toBeInTheDocument()
    expect(screen.getByText("平時")).toBeInTheDocument()
    // 檔案區：PDF 可預覽 → 預覽 + 下載
    expect(screen.getByText("SOP-v2.1.pdf")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "預覽" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下載" })).toBeInTheDocument()
  })

  it("編輯者：顯示「編輯新版本」/「廢止此文件」入口", async () => {
    renderWithProviders(<DmDetailPage />)
    expect(await screen.findByRole("button", { name: "編輯新版本" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "廢止此文件" })).toBeInTheDocument()
  })

  it("非編輯者（is_editor=false）→ 無編輯/廢止入口", async () => {
    server.use(
      http.get("/api/dm/documents/:docId", ({ params }) =>
        HttpResponse.json({
          doc_id: params.docId,
          doc_name: "只讀文件",
          status: "PUBLISHED",
          current_version_no: "1.0",
          category_code: "SOP",
          category_name: "SOP",
          author_id: "u1",
          author_name: "陳大華",
          published_date: "2026-04-15T10:30:00Z",
          approver_id: null,
          approver_name: null,
          approve_time: null,
          tags: [],
          func_code: null,
          func_name: null,
          file: {
            version_id: 1,
            file_name: "a.pdf",
            file_mime: "application/pdf",
            file_size: 1000,
            uploaded_at: null,
            previewable: true,
          },
          is_editor: false,
          can_edit: false,
          edit_lock_reason: null,
          is_obsolete: false,
          obsolete_info: null,
        }),
      ),
    )
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("只讀文件")
    expect(screen.queryByRole("button", { name: "編輯新版本" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "廢止此文件" })).not.toBeInTheDocument()
  })

  it("編輯者且送審中：入口顯示但灰階（disabled），非隱藏", async () => {
    server.use(
      http.get("/api/dm/documents/:docId", ({ params }) =>
        HttpResponse.json({
          doc_id: params.docId,
          doc_name: "送審中文件",
          status: "PUBLISHED",
          current_version_no: "1.0",
          category_code: "SOP",
          category_name: "SOP",
          author_id: "u1",
          author_name: "陳大華",
          published_date: "2026-04-15T10:30:00Z",
          approver_id: null,
          approver_name: null,
          approve_time: null,
          tags: [],
          func_code: null,
          func_name: null,
          file: {
            version_id: 1,
            file_name: "a.pdf",
            file_mime: "application/pdf",
            file_size: 1000,
            uploaded_at: null,
            previewable: true,
          },
          is_editor: true,
          can_edit: false,
          edit_lock_reason: "此文件新版本送審中，暫無法編輯或廢止",
          is_obsolete: false,
          obsolete_info: null,
        }),
      ),
    )
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("送審中文件")
    expect(await screen.findByRole("button", { name: "編輯新版本" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "廢止此文件" })).toBeDisabled()
  })

  it("版本歷程：展開列所有版本；目前版可下載、舊版僅預覽", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("領血確認標準作業程序")
    await user.click(screen.getByRole("button", { name: "版本歷程" }))
    expect(await screen.findByText("2.1")).toBeInTheDocument()
    expect(screen.getByText("2.0")).toBeInTheDocument()
    expect(screen.getByText("目前發布版本")).toBeInTheDocument()
    expect(screen.getByText("已被取代")).toBeInTheDocument()
  })

  it("Office 檔：不提供預覽、顯示下載提示", async () => {
    server.use(
      http.get("/api/dm/documents/:docId", ({ params }) =>
        HttpResponse.json({
          doc_id: params.docId,
          doc_name: "Word文件",
          status: "PUBLISHED",
          current_version_no: "1.0",
          category_code: "SOP",
          category_name: "SOP",
          author_id: "u1",
          author_name: "陳大華",
          published_date: null,
          approver_id: null,
          approver_name: null,
          approve_time: null,
          tags: [],
          func_code: null,
          func_name: null,
          file: {
            version_id: 1,
            file_name: "a.docx",
            file_mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size: 1000,
            uploaded_at: null,
            previewable: false,
          },
          can_edit: false,
          is_obsolete: false,
          obsolete_info: null,
        }),
      ),
    )
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("Word文件")
    expect(screen.getByText(/無法線上預覽/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "預覽" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下載" })).toBeInTheDocument()
  })

  it("已廢止 read-only：紅色 banner + 隱藏檔案/資訊 + 版本歷程自動展開", async () => {
    server.use(
      http.get("/api/dm/documents/:docId", ({ params }) =>
        HttpResponse.json({
          doc_id: params.docId,
          doc_name: "廢止文件",
          status: "OBSOLETE",
          current_version_no: "3.0",
          category_code: "SOP",
          category_name: "SOP",
          author_id: "u1",
          author_name: "陳大華",
          published_date: null,
          approver_id: null,
          approver_name: null,
          approve_time: null,
          tags: [],
          func_code: null,
          func_name: null,
          file: {
            version_id: 3,
            file_name: "a.pdf",
            file_mime: "application/pdf",
            file_size: 1000,
            uploaded_at: null,
            previewable: true,
          },
          can_edit: false,
          is_obsolete: true,
          obsolete_info: {
            review_id: 77,
            obsolete_time: "2026-04-10T11:15:00Z",
            applicant_id: "u1",
            applicant_name: "王曉明",
            approver_name: "李主任",
            reason: "院內停用",
            has_attachment: true,
            attachment_name: "函文.pdf",
          },
        }),
      ),
    )
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("廢止文件")
    expect(screen.getByText(/僅供稽核查閱/)).toBeInTheDocument()
    expect(screen.getByText(/院內停用/)).toBeInTheDocument()
    // 檔案區隱藏（不出現「文件檔案」標題）
    expect(screen.queryByText("文件檔案")).not.toBeInTheDocument()
    // 版本歷程自動展開（read-only 提示）
    expect(await screen.findByText(/已廢止：所有版本僅供預覽/)).toBeInTheDocument()
    await screen.findByText("2.1") // 版本載入
    // read-only：可預覽版本僅預覽、無版本檔下載鈕
    expect(screen.queryByRole("button", { name: "下載" })).not.toBeInTheDocument()
    // US10：返回鈕改為「返回已廢止文件查詢」、隱藏「版本歷程」toggle、提供廢止附件下載
    expect(screen.getByRole("button", { name: "返回已廢止文件查詢" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "返回文件庫" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "版本歷程" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下載廢止附件" })).toBeInTheDocument()
  })

  it("已廢止 read-only：無法預覽（Office）版本開放下載（SA 裁示）", async () => {
    server.use(
      http.get("/api/dm/documents/:docId", ({ params }) =>
        HttpResponse.json({
          doc_id: params.docId,
          doc_name: "廢止Word文件",
          status: "OBSOLETE",
          current_version_no: "1.0",
          category_code: "SOP",
          category_name: "SOP",
          author_id: "u1",
          author_name: "陳大華",
          published_date: null,
          approver_id: null,
          approver_name: null,
          approve_time: null,
          tags: [],
          func_code: null,
          func_name: null,
          file: {
            version_id: 9,
            file_name: "a.docx",
            file_mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size: 1000,
            uploaded_at: null,
            previewable: false,
          },
          can_edit: false,
          is_obsolete: true,
          obsolete_info: {
            review_id: 78,
            obsolete_time: "2026-04-10T11:15:00Z",
            applicant_id: "u1",
            applicant_name: "王曉明",
            approver_name: "李主任",
            reason: "停用",
            has_attachment: false,
            attachment_name: null,
          },
        }),
      ),
      http.get("/api/dm/documents/:docId/versions", () =>
        HttpResponse.json([
          {
            version_id: 9,
            version_no: "1.0",
            change_summary: "首版",
            file_name: "a.docx",
            author_id: "u1",
            author_name: "陳大華",
            approver_name: "李主任",
            published_date: "2026-02-10T14:20:00Z",
            is_current: true,
            previewable: false,
          },
        ]),
      ),
    )
    renderWithProviders(<DmDetailPage />)
    await screen.findByText("廢止Word文件")
    await screen.findByText("1.0") // 版本載入
    // Office（無法預覽）→ 無預覽鈕、有下載鈕
    expect(screen.queryByRole("button", { name: "預覽" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下載" })).toBeInTheDocument()
  })

  it("編輯者發起廢止：填原因 + 選審核者 → 送出成功提示（US8）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmDetailPage />)
    await user.click(await screen.findByRole("button", { name: "廢止此文件" }))
    expect(await screen.findByText("申請廢止文件")).toBeInTheDocument()
    await user.type(screen.getByRole("textbox", { name: /廢止原因/ }), "流程已停辦")
    await user.click(screen.getByRole("combobox", { name: /指定審核者/ }))
    await user.click(await screen.findByRole("option", { name: "王審核" }))
    await user.click(screen.getByRole("button", { name: "送出廢止申請" }))
    expect(await screen.findByText("已送出廢止申請，已通知指定審核者")).toBeInTheDocument()
  })

  it("廢止對話框：未填原因即送出 → 顯示必填錯誤（US8 / DM-MSG-DM02-011）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<DmDetailPage />)
    await user.click(await screen.findByRole("button", { name: "廢止此文件" }))
    await screen.findByText("申請廢止文件")
    await user.click(screen.getByRole("button", { name: "送出廢止申請" }))
    expect(await screen.findByText("請填寫廢止原因")).toBeInTheDocument()
  })
})