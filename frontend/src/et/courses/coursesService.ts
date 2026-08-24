import { http } from "../../services/http"
import type { ChapterItem, CourseCreateResult, CourseDetail, CoursePayload, TagOption } from "./schemas"

/** ET02 課程骨架與章節編排 API（US3 / #202）。 */
export const coursesApi = {
  getDetail: async (courseId: number): Promise<CourseDetail> => {
    const { data } = await http.get<CourseDetail>(`/et/courses/${courseId}`)
    return data
  },

  /** 標籤下拉；帶 courseId 時另含該課程既有已掛之停用標籤（FR-ET-US3-03）。 */
  listTags: async (courseId?: number): Promise<TagOption[]> => {
    const { data } = await http.get<TagOption[]>("/et/tags", {
      params: courseId === undefined ? undefined : { course_id: courseId },
    })
    return data
  },

  create: async (payload: CoursePayload): Promise<CourseCreateResult> => {
    const { data } = await http.post<CourseCreateResult>("/et/courses", payload)
    return data
  },

  update: async (courseId: number, payload: CoursePayload & { version: number }): Promise<void> => {
    await http.put(`/et/courses/${courseId}`, payload)
  },

  remove: async (courseId: number): Promise<void> => {
    await http.delete(`/et/courses/${courseId}`)
  },

  addChapter: async (courseId: number, chapterName: string): Promise<ChapterItem> => {
    const { data } = await http.post<ChapterItem>(`/et/courses/${courseId}/chapters`, {
      chapter_name: chapterName,
    })
    return data
  },

  renameChapter: async (chapterId: number, chapterName: string, version: number): Promise<void> => {
    await http.put(`/et/chapters/${chapterId}`, { chapter_name: chapterName, version })
  },

  /** 重排送**完整順序陣列**（非相對移動），version 為**課程層**版本。 */
  reorderChapters: async (courseId: number, chapterIds: number[], version: number): Promise<void> => {
    await http.put(`/et/courses/${courseId}/chapters/order`, { chapter_ids: chapterIds, version })
  },

  deleteChapter: async (chapterId: number): Promise<void> => {
    await http.delete(`/et/chapters/${chapterId}`)
  },
}
