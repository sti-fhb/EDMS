import { http } from "../../services/http"
import type { LearnStructure, MaterialContent } from "./learnSchemas"

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
