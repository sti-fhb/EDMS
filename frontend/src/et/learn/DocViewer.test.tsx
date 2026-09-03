import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { DocViewer } from "./DocViewer"
import { fetchDocBlob } from "./learnService"
import type { MaterialDocRow } from "./learnSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

// blob 取檔走 axios responseType:"blob"，jsdom + MSW(XHR) 對 Blob 支援不完整——
// partial-mock 取檔函式即可驗呈現分支（比照 `DmChangeLogPage.test.tsx` 之既有作法）。
vi.mock("./learnService", async (orig) => {
  const actual = await orig<typeof import("./learnService")>()
  return { ...actual, fetchDocBlob: vi.fn(async () => new Blob(["x"], { type: "application/pdf" })) }
})

function makeDoc(overrides: Partial<MaterialDocRow> = {}): MaterialDocRow {
  return {
    doc_id: "DM-SOP-000001",
    doc_name: "採血標準作業程序",
    file_name: "SOP-v2.1.pdf",
    file_mime: "application/pdf",
    version_id: 21,
    obsolete: false,
    previewable: true,
    available: true,
    sort_order: 1,
    ...overrides,
  }
}

describe("ET05 DM 文件呈現", () => {
  it("PDF 於頁內嵌入預覽（AC 15）", async () => {
    renderWithProviders(<DocViewer materialId={1} doc={makeDoc()} />)

    await waitFor(() => expect(screen.getByTitle("採血標準作業程序")).toBeInTheDocument())
    expect(screen.getByTitle("採血標準作業程序").tagName).toBe("IFRAME")
  })

  it("非 PDF 提供下載原檔連結（AC 16）", async () => {
    renderWithProviders(
      <DocViewer
        materialId={1}
        doc={makeDoc({ previewable: false, file_mime: "application/vnd.ms-excel", file_name: "檢核表.xlsx" })}
      />,
    )

    expect(screen.getByRole("button", { name: /下載原檔/ })).toBeInTheDocument()
    // 非 PDF 不該同時出現內嵌預覽
    expect(screen.queryByTitle("採血標準作業程序")).not.toBeInTheDocument()
  })

  it("已廢止顯示標籤但仍可閱讀（AC 17）", async () => {
    renderWithProviders(<DocViewer materialId={1} doc={makeDoc({ obsolete: true })} />)

    expect(screen.getByText("此文件已廢止")).toBeInTheDocument()
    // 標籤是提醒、不是阻擋——廢止前最後版本仍要看得到
    await waitFor(() => expect(screen.getByTitle("採血標準作業程序")).toBeInTheDocument())
  })

  it("實體檔不存在時訊息要指向原因", async () => {
    // 「文件載入失敗」四個字讓人無從下手——實測時就是被它卡住的。
    // DB 有 metadata 但檔案不在（DB↔磁碟不一致）會回 404，那是最常見的情形。
    const axiosLike = { response: { status: 404, data: new Blob() } }
    vi.mocked(fetchDocBlob).mockRejectedValueOnce(axiosLike)
    renderWithProviders(<DocViewer materialId={1} doc={makeDoc()} />)

    expect(await screen.findByText(/檔案已不存在/)).toBeInTheDocument()
  })

  it("DM 端取不到時顯示說明而非壞掉的連結", async () => {
    renderWithProviders(
      <DocViewer materialId={1} doc={makeDoc({ available: false, previewable: false, doc_name: null })} />,
    )

    expect(screen.getByText(/此文件目前無法取得/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /下載原檔/ })).not.toBeInTheDocument()
  })
})
