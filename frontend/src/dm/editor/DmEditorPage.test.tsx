import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DmEditorPage } from "./DmEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// useParams 可變（切換新增 / 編輯模式）；useNavigate 監看導向
const { navigateSpy, paramsRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    // MemoryRouter 非 data router，useBlocker 會拋錯；測試以永不攔截取代（離開攔截屬 e2e 行為）
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

const PDF = "application/pdf"
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

function pdfFile() {
  return new File(["%PDF-1.4 x"], "a.pdf", { type: PDF })
}

function fileInput(): HTMLInputElement {
  return document.querySelector('input[type="file"]') as HTMLInputElement
}

/** 新增模式：填妥所有送簽必填（名稱 / 分類 / 版號 / 摘要 / 審核者 / 檔案），可選是否加可見對象。 */
async function fillNewForm(user: ReturnType<typeof userEvent.setup>, { withAudience }: { withAudience: boolean }) {
  await user.type(screen.getByLabelText(/文件名稱/), "領血SOP")
  await user.click(screen.getByRole("combobox", { name: /分類/ }))
  await user.click(await screen.findByRole("option", { name: "標準作業程序" }))
  await user.type(screen.getByLabelText(/首版版本號/), "1.0")
  await user.type(screen.getByLabelText(/首版摘要/), "首版內容")
  await user.click(screen.getByRole("combobox", { name: /指定審核者/ }))
  await user.click(await screen.findByRole("option", { name: "王審核" }))
  if (withAudience) {
    await user.click(screen.getByRole("combobox", { name: /可見對象/ }))
    await user.click(await screen.findByRole("option", { name: "全體" }))
  }
  await user.upload(fileInput(), pdfFile())
}

beforeEach(() => {
  paramsRef.current = {}
  navigateSpy.mockClear()
})

describe("DmEditorPage 文件新增與編輯（DM03）", () => {
  it("新增模式：可編輯名稱；選『系統操作手冊』條件式顯示關聯作業項目", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    expect(await screen.findByText("新增文件")).toBeInTheDocument()
    expect(screen.getByLabelText(/文件名稱/)).toBeEnabled()
    // 預設非手冊類 → 無 func 下拉
    expect(screen.queryByRole("combobox", { name: /關聯作業項目/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "系統操作手冊" }))
    expect(await screen.findByRole("combobox", { name: /關聯作業項目/ })).toBeInTheDocument()
  })

  it("上傳 Office 檔 → 橘色無法預覽警示 + 二次確認", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.upload(fileInput(), new File(["x"], "a.docx", { type: DOCX }))
    expect(await screen.findByText(/此檔案格式.*無法線上預覽/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "仍使用此檔案" })).toBeInTheDocument()
  })

  it("送簽缺可見對象 → 顯示可見對象錯誤、不送出（DM-MSG-DM03-008）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await fillNewForm(user, { withAudience: false })
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("請至少指定 1 個可見對象")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 20000)

  it("送簽成功 → toast 已送交簽核並導向詳細（DM-MSG-DM03-006）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await fillNewForm(user, { withAudience: true })
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("已送交簽核，已通知指定審核者")).toBeInTheDocument()
    expect(navigateSpy).toHaveBeenCalledWith("/dm/library") // 新增模式送出後回文件庫（草稿/送審中不在詳細頁）
  }, 20000)

  it("送簽失敗後改審核者重試 → 不重複建立文件（HIGH #1 迴歸）", async () => {
    let createCalls = 0
    let submitCalls = 0
    server.use(
      http.post("/api/dm/documents", () => {
        createCalls += 1
        return HttpResponse.json({ doc_id: "DM-SOP-000009", version_id: 900, previewable: true }, { status: 201 })
      }),
      http.post("/api/dm/documents/:docId/submit", () => {
        submitCalls += 1
        if (submitCalls === 1) {
          return HttpResponse.json(
            { error_code: "DM_REVIEW_001", error_message: "指定審核者不可為文件撰寫者本人" },
            { status: 422 },
          )
        }
        return HttpResponse.json({ review_id: 500, notified: 1 })
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await fillNewForm(user, { withAudience: true }) // 預設選「王審核」
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("指定審核者不可為文件撰寫者本人")).toBeInTheDocument()
    // 改選另一位審核者後重試
    await user.click(screen.getByRole("combobox", { name: /指定審核者/ }))
    await user.click(await screen.findByRole("option", { name: "李審核" }))
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("已送交簽核，已通知指定審核者")).toBeInTheDocument()
    expect(createCalls).toBe(1) // 關鍵：改審核者不清草稿快取、不重複建立文件
  }, 20000)

  it("存草稿成功（可見對象非必填）→ toast 已儲存為草稿（DM-MSG-DM03-007）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.type(screen.getByLabelText(/文件名稱/), "草稿SOP")
    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "標準作業程序" }))
    await user.type(screen.getByLabelText(/首版版本號/), "0.1")
    await user.type(screen.getByLabelText(/首版摘要/), "草稿")
    await user.upload(fileInput(), pdfFile())
    await user.click(screen.getByRole("button", { name: "儲存為草稿" }))
    expect(await screen.findByText("已儲存為草稿")).toBeInTheDocument()
    expect(navigateSpy).toHaveBeenCalledWith("/dm/library")
  }, 20000)

  it("存草稿不卡必填：只選分類、不填版號/摘要/不傳檔 → 仍可存草稿", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    // 只選分類，版號/摘要留空、不上傳檔案
    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "標準作業程序" }))
    await user.click(screen.getByRole("button", { name: "儲存為草稿" }))
    expect(await screen.findByText("已儲存為草稿")).toBeInTheDocument()
    expect(navigateSpy).toHaveBeenCalledWith("/dm/library")
  }, 20000)

  it("送簽仍要求版號/摘要/檔案（存草稿放行、送簽才卡）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "標準作業程序" }))
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("請輸入版本號")).toBeInTheDocument()
    expect(screen.getByText("請輸入變更摘要")).toBeInTheDocument()
    expect(screen.getByText("請選擇要上傳的檔案")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 20000)

  it("版號重複（後端 DM_DOC_006）→ inline 標於版本號欄（DM-MSG-DM03-009）", async () => {
    server.use(
      http.post("/api/dm/documents", () =>
        HttpResponse.json(
          { error_code: "DM_DOC_006", error_message: "版本號未填或與本文件既有版本重複" },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await fillNewForm(user, { withAudience: true })
    await user.click(screen.getByRole("button", { name: "送交簽核" }))
    expect(await screen.findByText("版本號未填或與本文件既有版本重複")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 20000)

  it("編輯模式：身份欄唯讀、可見對象可改且預帶既有、顯示最近版本", async () => {
    paramsRef.current = { docId: "DM-SOP-000001" }
    renderWithProviders(<DmEditorPage />)
    expect(await screen.findByText(/編輯文件 —/)).toBeInTheDocument()
    expect(screen.getByLabelText(/文件名稱/)).toBeDisabled()
    // 可見對象下拉存在且預帶文件既有標籤（tags 端點回 audience_ids=["1"]＝全體）
    expect(screen.getByRole("combobox", { name: /可見對象/ })).toBeInTheDocument()
    expect(await screen.findByText("全體")).toBeInTheDocument() // 預帶的可見對象 chip
    // 最近版本面板（來自 US4 versions 端點：2.1 目前發布版 + 2.0 已被取代）
    expect(await screen.findByText("最近版本")).toBeInTheDocument()
    expect(screen.getByText("目前發布版")).toBeInTheDocument()
  })

  it("取消且有未存變更 → 二次確認（DM-MSG-DM03-005）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.type(screen.getByLabelText(/文件名稱/), "改了一點")
    await user.click(screen.getByRole("button", { name: "取消" }))
    expect(await screen.findByText(/編輯項目將不會保留/)).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  })
})