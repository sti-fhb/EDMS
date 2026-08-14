import type { DetailResponse, VersionItem } from "./schemas"
import { http } from "../../services/http"

/**
 * 文件詳細頁 API（US4，唯讀 + 檔案存取）。
 * 檔案下載 / 預覽以 blob 取得（帶 Authorization header，JWT 為 memory-only、無法用 <a href> 帶 token）。
 */
export const detailApi = {
  getDetail: async (docId: string): Promise<DetailResponse> => {
    const { data } = await http.get<DetailResponse>(`/dm/documents/${docId}`)
    return data
  },

  getVersions: async (docId: string): Promise<VersionItem[]> => {
    const { data } = await http.get<VersionItem[]>(`/dm/documents/${docId}/versions`)
    return data
  },

  fetchFileBlob: async (docId: string, versionId: number, disposition: "preview" | "download"): Promise<Blob> => {
    const { data } = await http.get<Blob>(`/dm/documents/${docId}/versions/${versionId}/file`, {
      params: { disposition },
      responseType: "blob",
    })
    return data
  },
}

/** 下載目前發布版：取 blob → 觸發瀏覽器下載（後端同時寫 DM_DOC_READ）。 */
export async function downloadVersionFile(docId: string, versionId: number, filename: string): Promise<void> {
  const blob = await detailApi.fetchFileBlob(docId, versionId, "download")
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 線上預覽（PDF / 圖片）：取 blob → 於新分頁開啟（預覽不寫閱讀紀錄）。 */
export async function previewVersionFile(docId: string, versionId: number): Promise<void> {
  const blob = await detailApi.fetchFileBlob(docId, versionId, "preview")
  const url = URL.createObjectURL(blob)
  window.open(url, "_blank", "noopener")
  // 延遲回收 blob URL：確保新分頁已載入後才釋放，避免記憶體洩漏（多次預覽累積）。
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}