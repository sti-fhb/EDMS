import { http } from "../../services/http"
import type { LearnStructure, MaterialContent, VideoTicket } from "./learnSchemas"

/** ET05 章節學習 API（US5 / #255）。 */
export const learnApi = {
  structure: async (courseId: number): Promise<LearnStructure> => {
    const { data } = await http.get<LearnStructure>(`/et/courses/${courseId}/learn`)
    return data
  },

  materialContent: async (materialId: number): Promise<MaterialContent> => {
    const { data } = await http.get<MaterialContent>(`/et/materials/${materialId}/content`)
    return data
  },
}

/**
 * 取影片播放票（60 秒、綁單一影片）。
 *
 * `<video src>` 送不出 Authorization header，而影片單檔上限 500MB 不能用 blob
 * （整支下載完才能播、失去 Range）。故以票放進 query string——形同 S3 presigned URL。
 */
export async function requestVideoTicket(videoId: number): Promise<string> {
  const { data } = await http.post<VideoTicket>(`/et/videos/${videoId}/ticket`)
  return data.ticket
}

/**
 * 影片檔 URL（**憑票**）。
 *
 * 直接放進 `<video src>`，拖動進度條所需的 Range 請求由瀏覽器自行發出、後端以
 * `FileResponse` 支援。**不經 axios**——那會變成 blob，失去串流與 Range。
 *
 * base URL 取自 `http` client 而非硬寫 `/api`：`VITE_API_BASE_URL` 是可設定的
 * （見 `.env.example`），硬寫會讓「全站唯一一條不經 axios 的路徑」在後端換位址時
 * 與其餘 API 不一致而失效。
 */
export function videoFileUrl(videoId: number, ticket: string): string {
  const base = (http.defaults.baseURL ?? "").replace(/\/$/, "")
  return `${base}/et/videos/${videoId}/file?t=${encodeURIComponent(ticket)}`
}

/**
 * 取 DM 文件之 blob（PDF 供 `<iframe>` 內嵌、其餘供下載）。
 *
 * **必須經 axios 取 blob，不能把 URL 直接放進 `src` / `href`**：JWT 是 memory-only
 * （刻意不落 cookie），`<iframe>` / `<a>` 不會帶 Authorization header，直接放 URL 會
 * 401。比照 DM `detail/detailService.fetchFileBlob` 之既有作法。
 */
export async function fetchDocBlob(materialId: number, docId: string): Promise<Blob> {
  const { data } = await http.get<Blob>(`/et/materials/${materialId}/docs/${encodeURIComponent(docId)}/file`, {
    responseType: "blob",
  })
  return data
}
