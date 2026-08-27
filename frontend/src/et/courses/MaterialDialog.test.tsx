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
  }
  renderWithProviders(
    <MaterialDialog
      open
      loading={false}
      readOnly={false}
      material={material}
      dmOptions={[]}
      error={null}
      uploadError={null}
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

  it("儲存時送出完整媒材狀態", async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "儲存" }))

    expect(onSave).toHaveBeenCalledWith({
      material_name: "採血示範",
      description_html: "<p>本教材重點</p>",
      doc_ids: ["DM-TRAINING-000201"],
      video_ids: [1],
    })
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

  it("移除影片只改本地狀態，按儲存才送出", async () => {
    // 逐筆即時刪除會讓「取消」失去意義，也繞過「至少擇一媒材」的檢核
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "移除影片 demo.mp4" }))

    expect(screen.queryByText("demo.mp4")).not.toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "儲存" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ video_ids: [] }))
  })

  it("移除文件引用只改本地狀態，按儲存才送出", async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "移除文件引用 DM-TRAINING-000201" }))

    expect(screen.queryByText("採血流程訓練教材")).not.toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "儲存" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ doc_ids: [] }))
  })

  it("取消時回報有未儲存變更，交由呼叫端確認", async () => {
    const user = userEvent.setup()
    const { onClose, onSave } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "移除文件引用 DM-TRAINING-000201" }))
    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(onClose).toHaveBeenCalledWith(true)
    expect(onSave).not.toHaveBeenCalled()
  })

  it("沒有改動時取消不回報 dirty——沒改過還問一次是干擾", async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog()
    await user.click(await screen.findByRole("button", { name: "取消" }))
    expect(onClose).toHaveBeenCalledWith(false)
  })

  it("加入 DM 文件只改本地狀態，按儲存才送出", async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog({
      dmOptions: [
        { doc_id: "DM-TRAINING-000999", doc_name: "新文件", version_no: "v1.0", published_date: null },
      ],
    })
    await user.click(await screen.findByRole("combobox", { name: /從 DM/ }))
    await user.click(await screen.findByRole("option", { name: /新文件/ }))

    expect(onSave).not.toHaveBeenCalled()
    await user.click(screen.getByRole("button", { name: "儲存" }))
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ doc_ids: ["DM-TRAINING-000201", "DM-TRAINING-000999"] }),
    )
  })

  it("上傳中停用儲存並於拖放區顯示進度", async () => {
    renderDialog({ uploading: true })
    expect(await screen.findByText("上傳中⋯")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled()
  })

  it("同名影片於前端先擋下，不送出上傳", async () => {
    // 後端也擋（ET_MATERIAL_005），但那要先把整支檔案傳上去才知道——單檔上限 500 MB
    const user = userEvent.setup()
    const { onUploadVideo } = renderDialog()
    const input = screen.getByLabelText("選擇影片檔")
    await user.upload(input, new File(["x"], "demo.mp4", { type: "video/mp4" }))

    expect(onUploadVideo).not.toHaveBeenCalled()
    expect(await screen.findByRole("alert")).toHaveTextContent("此教材已有同名影片")
  })

  it("上傳錯誤顯示於上傳區旁，不在視窗頂端", async () => {
    // 使用者按下上傳時視線在上傳區，訊息飄到最上面等於沒說——他只會覺得傳不上去
    renderDialog({ uploadError: "無法解析影片長度，請改用其他格式" })
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("無法解析影片長度")

    // 與上傳區同一區塊：兩者共同的祖先不應是整個對話框內容
    const dropzone = screen.getByRole("button", { name: "拖拉或點擊選擇影片檔" })
    expect(alert.parentElement).toBe(dropzone.parentElement)
  })

  it("不同檔名照常上傳", async () => {
    const user = userEvent.setup()
    const { onUploadVideo } = renderDialog()
    const input = screen.getByLabelText("選擇影片檔")
    await user.upload(input, new File(["x"], "another.mp4", { type: "video/mp4" }))

    expect(onUploadVideo).toHaveBeenCalled()
  })

  it("提供拖拉上傳區", async () => {
    renderDialog()
    expect(await screen.findByRole("button", { name: "拖拉或點擊選擇影片檔" })).toBeInTheDocument()
    expect(screen.getByText(/支援 mp4 \/ webm，單檔最大 500 MB/)).toBeInTheDocument()
  })

  it("唯讀模式不顯示儲存與刪除入口", async () => {
    renderDialog({ readOnly: true })
    expect(await screen.findByRole("button", { name: "關閉" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /移除影片/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /移除文件引用/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "拖拉或點擊選擇影片檔" })).not.toBeInTheDocument()
  })
})
