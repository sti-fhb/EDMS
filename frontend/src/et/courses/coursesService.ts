import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"
import type {
  Capabilities,
  CourseCard,
  CourseListParams,
  ChapterItem,
  CourseCreatePayload,
  CourseCreateResult,
  CourseDetail,
  CoursePayload,
  CourseStatusResult,
  ReopenPayload,
  TagOption,
} from "./schemas"

/** ET02 課程骨架與章節編排 API（US3 / #202）。 */
export const coursesApi = {
  /** 當前使用者之課程操作能力（回「能力」而非「角色」，比照 DM `Capabilities`）。 */
  getCapabilities: async (): Promise<Capabilities> => {
    const { data } = await http.get<Capabilities>("/et/courses/capabilities")
    return data
  },

  /**
   * ET01 課程清單（US7 / #299）。
   *
   * `scope` 決定狀態過濾且兩者相反：`mine` 含草稿與已關閉（教師要管理自己的課），
   * `all` 僅已發布（草稿的存在對他人是秘密）。
   */
  list: async (params: CourseListParams): Promise<PagedResult<CourseCard>> => {
    const { data } = await http.get<PagedResult<CourseCard>>("/et/courses", { params })
    return data
  },

  /**
   * ET01 篩選用的標籤下拉：**全部含停用者**。
   *
   * ⚠️ 與 `listTags()` 語意相反、不可互換——那支是 ET02 編輯時掛標籤用的（停用者不得
   * 新掛故排除）。用錯會讓掛著已停用標籤的歷史課程搜不到，而畫面上沒有任何異常。
   */
  listFilterTags: async (): Promise<TagOption[]> => {
    const { data } = await http.get<TagOption[]>("/et/courses/filter-tags")
    return data
  },

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

  create: async (payload: CourseCreatePayload): Promise<CourseCreateResult> => {
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

  /**
   * 關閉課程（US11 AC 1 / #288）——僅已發布課程可關閉。
   *
   * 具名動作而非 `PUT` 改 `status`：狀態轉換有自己的前提與副作用（寫 `CLOSED_AT`），
   * 走 `PUT` 會讓 `status` 變成可任意賦值的欄位而繞過整個狀態機。
   */
  close: async (courseId: number, version: number): Promise<CourseStatusResult> => {
    const { data } = await http.post<CourseStatusResult>(`/et/courses/${courseId}/close`, { version })
    return data
  },

  /**
   * 再開課（US11 AC 8 / #288）——**強制帶一組新起訖時間**。
   *
   * 會重跑發布六項檢核（SA Q2 裁示 A）：關閉期間教師端仍可編輯內容，課程可能已不符
   * 發布條件，不合格回 422 `ET_PUBLISH_001` + `blockers`（與 `publish` 同形狀）。
   */
  reopen: async (courseId: number, payload: ReopenPayload): Promise<CourseStatusResult> => {
    const { data } = await http.post<CourseStatusResult>(`/et/courses/${courseId}/reopen`, payload)
    return data
  },
}
