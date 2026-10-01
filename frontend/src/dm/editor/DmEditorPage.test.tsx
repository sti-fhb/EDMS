import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { delay, http, HttpResponse } from "msw"
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

/**
 * 新增一組可見對象 (單位, 職位) 配對（#437）：先按「新增可見對象」長出一列，再各選一端。
 * 兩個 combobox 以 label「單位」/「職位」定位；多列時取最後一組（新長出的那列）。
 */
/**
 * 填入一組可見對象 (單位, 職位) 配對。
 *
 * 表單**預設已帶一列空白**（#476），故先找有沒有還沒選單位的列可用；都填滿了才按「新增可見對象」。
 * 若無條件先按「新增」，預設那列會留白——送簽時它會被擋下（兩欄皆必填），測試就紅在不相干的地方。
 */
async function addAudiencePair(
  user: ReturnType<typeof userEvent.setup>,
  { unit, role }: { unit: string; role: string },
) {
  const blankIdx = screen
    .getAllByRole("combobox", { name: /單位/ })
    .findIndex((el) => (el as HTMLInputElement).value === "")
  if (blankIdx < 0) await user.click(screen.getByRole("button", { name: "新增可見對象" }))
  const idx = blankIdx < 0 ? screen.getAllByRole("combobox", { name: /單位/ }).length - 1 : blankIdx

  await user.click(screen.getAllByRole("combobox", { name: /單位/ })[idx])
  await user.click(await screen.findByRole("option", { name: unit }))
  await user.click(screen.getAllByRole("combobox", { name: /職位/ })[idx])
  await user.click(await screen.findByRole("option", { name: role }))
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
  if (withAudience) await addAudiencePair(user, { unit: "全單位", role: "全體" })
  await user.upload(fileInput(), pdfFile())
}

beforeEach(() => {
  paramsRef.current = {}
  navigateSpy.mockClear()
})

describe("DmEditorPage 文件新增與編輯（DM08）", () => {
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

  it("新增模式：可見對象預設帶一列配對，兩欄皆標示必填（#476）", async () => {
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")

    // 一進頁面就看得到要填什麼，不必先按「新增可見對象」
    const unit = screen.getByRole("combobox", { name: /單位/ })
    const role = screen.getByRole("combobox", { name: /職位/ })
    expect(unit).toBeInTheDocument()
    expect(role).toBeInTheDocument()
    // 與「文件名稱」等必填欄位一致：label 帶 * 且標記為必填
    expect(unit).toBeRequired()
    expect(role).toBeRequired()
    // 尚未送簽 → 不應預先標紅
    expect(unit).toHaveAttribute("aria-invalid", "false")
  }, 20000)

  it("上傳 Office 檔 → 橘色無法預覽警示 + 二次確認", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.upload(fileInput(), new File(["x"], "a.docx", { type: DOCX }))
    expect(await screen.findByText(/此檔案格式.*無法線上預覽/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "仍使用此檔案" })).toBeInTheDocument()
  })

  it("送簽缺可見對象 → 該列單位 / 職位欄位標紅、不送出（DM-MSG-DM08-008）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await fillNewForm(user, { withAudience: false })
    await user.click(screen.getByRole("button", { name: "送交簽核" }))

    // 錯誤由欄位自身呈現（#476）：MUI 的 error 會把 aria-invalid 設為 true，與其他必填欄位一致。
    // 不再於區塊下方另列紅字，故這裡刻意不找文字訊息——找得到反而表示又變回兩個地方各講一次。
    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: /單位/ })).toHaveAttribute("aria-invalid", "true")
    })
    expect(screen.getByRole("combobox", { name: /職位/ })).toHaveAttribute("aria-invalid", "true")
    expect(screen.queryByText("請選擇單位")).not.toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  }, 20000)

  it("存檔後重進編輯頁：標籤預帶新值，不被快取舊值鎖住（#377 手測回報）", async () => {
    paramsRef.current = { docId: "DM-SOP-000001" }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // 第一次進入：文件標籤為「全體」
    server.use(
      http.get("/api/dm/editor/documents/:docId/tags", () =>
        HttpResponse.json({ audience_pairs: [{ unit_id: "100", audience_id: "1" }], retrieval_ids: [] }),
      ),
    )
    const first = renderWithProviders(<DmEditorPage />, undefined, undefined, qc)
    expect(await screen.findByDisplayValue("全體")).toBeInTheDocument()
    first.unmount()

    // 模擬使用者改標籤並存檔後：伺服器端現在回「護理師」
    server.use(
      http.get("/api/dm/editor/documents/:docId/tags", () =>
        HttpResponse.json({ audience_pairs: [{ unit_id: "100", audience_id: "2" }], retrieval_ids: [] }),
      ),
    )
    renderWithProviders(<DmEditorPage />, undefined, undefined, qc)

    // 重進時 TanStack Query（staleTime 0）會先同步吐出快取的「全體」再背景 refetch；
    // 一次性預帶必須等 refetch 落定，否則 guard 會鎖住舊值 → 使用者以為沒存到。
    expect(await screen.findByDisplayValue("護理師")).toBeInTheDocument()
    expect(screen.queryByDisplayValue("全體")).not.toBeInTheDocument()
  }, 20000)

  it("refetch 期間已動手改標籤 → 落定後不覆蓋使用者的選擇（#396 補審之競態）", async () => {
    paramsRef.current = { docId: "DM-SOP-000001" }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // 第一次進入：填充快取（可見對象＝全體）
    server.use(
      http.get("/api/dm/editor/documents/:docId/tags", () =>
        HttpResponse.json({ audience_pairs: [{ unit_id: "100", audience_id: "1" }], retrieval_ids: [] }),
      ),
    )
    const first = renderWithProviders(<DmEditorPage />, undefined, undefined, qc)
    expect(await screen.findByDisplayValue("全體")).toBeInTheDocument()
    first.unmount()

    // 第二次進入：伺服器仍回「全體」但刻意延遲。有快取 → 載入 gate 不擋，表單此時已可互動，
    // 使用者搶在 refetch 落定前改成「護理師」；落定後不得被伺服器值蓋回去。
    server.use(
      http.get("/api/dm/editor/documents/:docId/tags", async () => {
        await delay(400)
        return HttpResponse.json({ audience_pairs: [{ unit_id: "100", audience_id: "1" }], retrieval_ids: [] })
      }),
    )
    renderWithProviders(<DmEditorPage />, undefined, undefined, qc)

    const user = userEvent.setup({ delay: null })
    // 配對列由資料驅動渲染（#437），refetch 落定前尚無列——使用者能做的是**自己新增一組**。
    // 驗的仍是同一件事：動手之後 guard 即鎖定，落定時不得用伺服器值覆蓋使用者的輸入。
    await screen.findByText("編輯文件 — 領血確認標準作業程序")
    await addAudiencePair(user, { unit: "國防部軍醫局", role: "護理師" })
    expect(screen.getByDisplayValue("護理師")).toBeInTheDocument()

    // 等 refetch 確定落定（超過上面的 400ms）後再斷言，確保驗到的是「落定後」的狀態
    await new Promise((r) => setTimeout(r, 700))
    expect(screen.getByDisplayValue("護理師")).toBeInTheDocument()
    expect(screen.getByDisplayValue("國防部軍醫局")).toBeInTheDocument()
    // 伺服器回的是 (全單位, 全體)；若 guard 失效會把使用者那列蓋掉
    expect(screen.queryByDisplayValue("全體")).not.toBeInTheDocument()
  }, 20000)

  it("分類選『訓練教材』→ 隱藏可見對象欄並說明不需設定（#377）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    expect(screen.getByRole("button", { name: "新增可見對象" })).toBeInTheDocument()

    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "訓練教材" }))

    expect(screen.queryByRole("button", { name: "新增可見對象" })).not.toBeInTheDocument()
    expect(screen.getByText("訓練教材由教育訓練模組引用，不需設定可見對象")).toBeInTheDocument()
  }, 20000)

  it("訓練教材未選可見對象仍可送簽（TRAINING 免填，#377）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.type(screen.getByLabelText(/文件名稱/), "用血回報訓練教材")
    await user.click(screen.getByRole("combobox", { name: /分類/ }))
    await user.click(await screen.findByRole("option", { name: "訓練教材" }))
    await user.type(screen.getByLabelText(/首版版本號/), "1.0")
    await user.type(screen.getByLabelText(/首版摘要/), "首版內容")
    await user.click(screen.getByRole("combobox", { name: /指定審核者/ }))
    await user.click(await screen.findByRole("option", { name: "王審核" }))
    await user.upload(fileInput(), pdfFile())

    await user.click(screen.getByRole("button", { name: "送交簽核" }))

    // 不出現 DM-MSG-DM08-008 的可見對象錯誤，直接送出成功
    expect(await screen.findByText("已送交簽核，已通知指定審核者")).toBeInTheDocument()
    expect(screen.queryByText("請至少指定 1 組可見對象")).not.toBeInTheDocument()
  }, 20000)

  it("送簽成功 → toast 已送交簽核並導向詳細（DM-MSG-DM08-006）", async () => {
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

  it("存草稿成功（可見對象非必填）→ toast 已儲存為草稿（DM-MSG-DM08-007）", async () => {
    // 本條同時守著 #476 的連動變更：表單預設帶一列空白配對，存草稿時那列**不得**被
    // 「請選擇單位」擋下（spec_us5 FR-001「存草稿不卡必填」）。若 Zod 在 forSubmit=false
    // 時又套回嚴格的 AudiencePairSchema，這裡會紅。
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

  it("版號重複（後端 DM_DOC_006）→ inline 標於版本號欄（DM-MSG-DM08-009）", async () => {
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
    // 可見對象配對列存在且預帶文件既有配對（tags 端點回 (全單位, 全體)）
    expect(screen.getByRole("button", { name: "新增可見對象" })).toBeInTheDocument()
    // 預帶的配對：(全單位, 全體) —— 兩端各自顯示於同一列的兩個下拉
    expect(await screen.findByDisplayValue("全單位")).toBeInTheDocument()
    expect(screen.getByDisplayValue("全體")).toBeInTheDocument()
    // 最近版本面板（來自 US4 versions 端點：2.1 目前發布版 + 2.0 已被取代）
    expect(await screen.findByText("最近版本")).toBeInTheDocument()
    expect(screen.getByText("目前發布版")).toBeInTheDocument()
  })

  it("續編首版草稿：名稱可編輯、帶出既有版號/摘要/檔名、儲存走更新既有版本（#222）", async () => {
    let putCalls = 0
    server.use(
      http.get("/api/dm/editor/documents/:docId/draft-meta", () =>
        HttpResponse.json({
          doc_id: "DM-SOP-000050",
          doc_name: "首版草稿A",
          category_code: "SOP",
          category_name: "標準作業程序",
          func_code: null,
          func_name: null,
          doc_status: "DRAFT",
          name_editable: true,
          draft_version_id: 555,
          version_no: "1.0",
          change_summary: "首版摘要草",
          file_name: "old.pdf",
          file_size: 100,
          previewable: true,
          assigned_reviewer: "rev1",
        }),
      ),
      http.put("/api/dm/documents/:docId/versions/:versionId", ({ params }) => {
        putCalls += 1
        return HttpResponse.json({ version_id: Number(params.versionId), previewable: true })
      }),
    )
    paramsRef.current = { docId: "DM-SOP-000050" }
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    expect(await screen.findByText("編輯文件 — 首版草稿A")).toBeInTheDocument()
    expect(screen.getByLabelText(/文件名稱/)).toBeEnabled() // 首版草稿名稱可改（Q1=A）
    expect(screen.getByLabelText(/新版本號/)).toHaveValue("1.0") // 帶出既有版號
    expect(screen.getByLabelText(/變更摘要/)).toHaveValue("首版摘要草") // 帶出既有摘要
    expect(await screen.findByText("王審核")).toBeInTheDocument() // 指定審核者預帶（Round-2）
    expect(screen.getByText(/已選擇：old.pdf/)).toBeInTheDocument() // 既有檔案以「已選擇」樣式呈現（Round-2 item3）
    await user.click(screen.getByRole("button", { name: "儲存為草稿" }))
    expect(await screen.findByText("已儲存為草稿")).toBeInTheDocument()
    expect(putCalls).toBe(1) // 續編走更新既有版本（PUT），非另開版本
    expect(navigateSpy).toHaveBeenCalledWith("/dm/me?tab=drafts") // 導回草稿匣（Round-1）
  }, 20000)

  it("續編新版本草稿：名稱唯讀、版號/摘要帶入上次草稿值（#308 推翻 Round-1 留白）", async () => {
    server.use(
      http.get("/api/dm/editor/documents/:docId/draft-meta", () =>
        HttpResponse.json({
          doc_id: "DM-SOP-000051",
          doc_name: "已發布B",
          category_code: "SOP",
          category_name: "標準作業程序",
          func_code: null,
          func_name: null,
          doc_status: "PUBLISHED",
          name_editable: false,
          draft_version_id: 556,
          version_no: "2.0-draft",
          change_summary: "新版草摘",
          file_name: "v2.pdf",
          file_size: 100,
          previewable: true,
          assigned_reviewer: null,
        }),
      ),
    )
    paramsRef.current = { docId: "DM-SOP-000051" }
    renderWithProviders(<DmEditorPage />)
    expect(await screen.findByText("編輯文件 — 已發布B")).toBeInTheDocument()
    expect(screen.getByLabelText(/文件名稱/)).toBeDisabled() // 已發布文件之新版草稿名稱唯讀
    // #308：改為一律帶入——版號重複已由送審的 version_no_taken 擋掉，留白只是讓使用者看不到上次寫了什麼
    expect(screen.getByLabelText(/新版本號/)).toHaveValue("2.0-draft")
    expect(screen.getByLabelText(/變更摘要/)).toHaveValue("新版草摘")
    // 取代留白原本的提醒作用
    expect(screen.getAllByText(/送審前請確認反映本次變更/).length).toBeGreaterThan(0)
  })

  it("續編已廢止孤兒草稿：顯示已廢止警示、鎖送簽/存草稿（#222 安全）", async () => {
    server.use(
      http.get("/api/dm/editor/documents/:docId/draft-meta", () =>
        HttpResponse.json({
          doc_id: "DM-SOP-000052",
          doc_name: "已廢止C",
          category_code: "SOP",
          category_name: "標準作業程序",
          func_code: null,
          func_name: null,
          doc_status: "OBSOLETE",
          name_editable: false,
          draft_version_id: 557,
          version_no: "2.0",
          change_summary: "孤兒",
          file_name: "c.pdf",
          file_size: 100,
          previewable: true,
          assigned_reviewer: null,
        }),
      ),
    )
    paramsRef.current = { docId: "DM-SOP-000052" }
    renderWithProviders(<DmEditorPage />)
    expect(await screen.findByText(/此文件已廢止，無法續編或送審/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "送交簽核" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "儲存為草稿" })).toBeDisabled()
  })

  it("取消且有未存變更 → 二次確認（DM-MSG-DM08-005）", async () => {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<DmEditorPage />)
    await screen.findByText("新增文件")
    await user.type(screen.getByLabelText(/文件名稱/), "改了一點")
    await user.click(screen.getByRole("button", { name: "取消" }))
    expect(await screen.findByText(/編輯項目將不會保留/)).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  })
})