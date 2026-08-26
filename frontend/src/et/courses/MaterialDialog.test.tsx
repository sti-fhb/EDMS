import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { MaterialDialog } from "./MaterialDialog"
import type { MaterialDetail } from "./itemSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const material: MaterialDetail = {
  material_id: 10,
  material_name: "採血示範",
  description_html: "<p>本教材重點</p>",
  version: 0,
  videos: [
    { video_id: 1, file_name: "demo.mp4", duration_sec: 945, file_size_bytes: 188743680, sort_order: 1 },
  ],
  docs: [
    {
      mat_doc_id: 1,
      doc_id: "DM-TRAINING-000201",
      doc_name: "採血流程訓練教材",
      version_no: "v2.0",
      obsolete: false,
      unavailable: false,
      sort_order: 1,
    },
  ],
}

function renderDialog(overrides: Partial<Parameters<typeof MaterialDialog>[0]> = {}) {
  const handlers = {
    onClose: vi.fn(),
    onSave: vi.fn(),
    onUploadVideo: vi.fn(),
    onDeleteVideo: vi.fn(),
    onAddDoc: vi.fn(),
    onDeleteDoc: vi.fn(),
  }
  renderWithProviders(
    <MaterialDialog
      open
      loading={false}
      readOnly={false}
      material={material}
      dmOptions={[]}
      error={null}
      uploading={false}
      {...handlers}
      {...overrides}
    />,
  )
  return handlers
}

describe("教材編輯視窗", () => {
  it("載入既有教材之名稱、影片與文件引用", async () => {
    renderDialog()
    expect(await screen.findByDisplayValue("採血示範")).toBeInTheDocument()
    expect(screen.getByText("demo.mp4")).toBeInTheDocument()
    expect(screen.getByText("採血流程訓練教材")).toBeInTheDocument()
  })

  it("影片顯示長度與檔案大小", () => {
    renderDialog()
    // 945 秒 = 15:45；188743680 bytes = 180 MB
    expect(screen.getByText(/180 MB ｜ 15:45/)).toBeInTheDocument()
  })

  it("廢止文件顯示常駐警告標記", () => {
    // 用 Chip 而非 snackbar：需要指出「是哪一筆」有問題
    renderDialog({
      material: { ...material, docs: [{ ...material.docs[0], obsolete: true }] },
    })
    expect(screen.getByText("此文件已廢止")).toBeInTheDocument()
  })

  it("DM 端取不到的引用另以「已失效」標記區辨", () => {
    // 與「已廢止」不同：廢止文件學員仍讀得到最後版，取不到的是真的沒東西
    renderDialog({
      material: {
        ...material,
        docs: [{ ...material.docs[0], doc_name: null, version_no: null, unavailable: true }],
      },
    })
    expect(screen.getByText("文件已失效")).toBeInTheDocument()
    expect(screen.queryByText("此文件已廢止")).not.toBeInTheDocument()
  })

  it("儲存時把名稱與說明文字交給呼叫端", async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ material_name: "採血示範", description_html: "<p>本教材重點</p>" }),
    )
  })

  it("說明文字為空殼標籤時送出 null", async () => {
    // TipTap 清空後留下 <p></p>。原樣送出會讓後端認定「有說明文字」，
    // 使三類媒材皆空的教材通過 ET_MATERIAL_002 的檢核。
    const user = userEvent.setup()
    const { onSave } = renderDialog({ material: { ...material, description_html: "<p></p>" } })
    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ description_html: null }))
  })

  it("三類媒材皆空時顯示提示", async () => {
    renderDialog({
      material: { ...material, description_html: null, videos: [], docs: [] },
    })
    expect(await screen.findByText(/教材須至少提供影片、文件或說明文字其中一項/)).toBeInTheDocument()
  })

  it("後端錯誤呈現在視窗內而非飄走", async () => {
    // 訊息需指出是哪一個教材出問題，snackbar 說不清楚
    renderDialog({ error: "教材須至少提供影片、文件或說明文字其中一項" })
    expect(await screen.findByRole("alert")).toHaveTextContent("教材須至少提供影片")
  })

  it("刪除影片時通知呼叫端", async () => {
    const user = userEvent.setup()
    const { onDeleteVideo } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "刪除影片 demo.mp4" }))
    expect(onDeleteVideo).toHaveBeenCalledWith(material.videos[0])
  })

  it("刪除文件引用時通知呼叫端", async () => {
    const user = userEvent.setup()
    const { onDeleteDoc } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "移除文件引用 DM-TRAINING-000201" }))
    expect(onDeleteDoc).toHaveBeenCalledWith(material.docs[0])
  })

  it("上傳中停用儲存與選檔按鈕", async () => {
    renderDialog({ uploading: true })
    expect(await screen.findByRole("button", { name: /上傳中/ })).toBeDisabled()
    expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled()
  })

  it("唯讀模式不顯示儲存與刪除入口", async () => {
    renderDialog({ readOnly: true })
    expect(await screen.findByRole("button", { name: "關閉" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /刪除影片/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /移除文件引用/ })).not.toBeInTheDocument()
  })
})
