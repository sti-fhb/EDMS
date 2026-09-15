import { http } from "../../services/http"
import type { PagedResult } from "../../hooks/usePagedQuery"
import type {
  AttemptOverview,
  StudentRow,
  SurveyResult,
  TeacherAttemptDetail,
} from "./schemas"

/** ET03 學員學習狀況追蹤 API（US9 / #322）。教師端，全部需課程擁有權。 */
export const studentsApi = {
  /** 區塊 1：已加入學員清單（分頁）。 */
  listStudents: async (courseId: number, params: { page?: number; limit?: number }): Promise<PagedResult<StudentRow>> => {
    const { data } = await http.get<PagedResult<StudentRow>>(`/et/courses/${courseId}/students`, { params })
    return data
  },

  /** 區塊 2：所有曾作答學員 × 各測驗之 attempt 摘要（**不分頁**）。 */
  attemptOverview: async (courseId: number): Promise<AttemptOverview> => {
    const { data } = await http.get<AttemptOverview>(`/et/courses/${courseId}/attempt-overview`)
    return data
  },

  /**
   * 區塊 2：教師端單次 attempt 之逐題明細。
   *
   * ⚠️ 與學員端 `/et/attempts/{id}/result` 是**不同端點**：那支只能看自己的，本支以
   * 課程擁有權判定，看的是別人的考卷。
   */
  attemptDetail: async (attemptId: number): Promise<TeacherAttemptDetail> => {
    const { data } = await http.get<TeacherAttemptDetail>(`/et/attempts/${attemptId}/detail`)
    return data
  },

  /** 區塊 3：問卷結果。`has_survey=false` 時前端不渲染整個區塊。 */
  surveyResult: async (courseId: number): Promise<SurveyResult> => {
    const { data } = await http.get<SurveyResult>(`/et/courses/${courseId}/survey-result`)
    return data
  },

  /**
   * 重置某學員於某測驗之重考次數。
   *
   * **以測驗為單位**，非整門課。是否可重置由後端的 `can_reset` 決定，前端只負責在
   * 不可重置時停用按鈕並說明原因。
   */
  resetRetry: async (courseId: number, userId: string, quizId: number): Promise<void> => {
    // `encodeURIComponent`：值目前來自後端回應故安全，但這是零成本的防禦
    await http.post(
      `/et/courses/${courseId}/students/${encodeURIComponent(userId)}/quizzes/${quizId}/retry-reset`,
    )
  },

  /** 移除學員（軟刪；學習歷史保留）。 */
  removeStudent: async (courseId: number, userId: string): Promise<void> => {
    await http.delete(`/et/courses/${courseId}/students/${encodeURIComponent(userId)}`)
  },
}

/**
 * 兩支 CSV 匯出——**必須經 axios 取 blob，不可用 `<a href>` 直接導覽**。
 *
 * 🔴 本專案的 access token 是 **memory-only Bearer**（見 `services/http.ts`：刻意不落
 * `localStorage`），只在 axios 的 request interceptor 注入；後端用 `HTTPBearer`，全站
 * **沒有 cookie 認證**。瀏覽器原生導覽不經 axios、不帶 header，那兩支匯出會直接 401。
 *
 * ⚠️ **不要改用 query string 帶 token 來「修好」它**——`et/learning/video_ticket.py` 的
 * docstring 已列出代價：nginx error_log、Cloudflare Tunnel（不受我方管轄）與瀏覽器歷史
 * 都會記下完整 URI。而這兩支匯出取得的是**全班具名問卷填答與個別成績**。
 *
 * 形狀照抄 `dm/kpi/kpiService.ts` 的 `downloadKpiCsv`（DM 三處匯出皆同一寫法）。
 */
async function downloadCsv(path: string, filename: string): Promise<void> {
  const { data } = await http.get<Blob>(path, { responseType: "blob" })
  const url = URL.createObjectURL(data)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 匯出區塊 1 之學員清單。 */
export async function downloadStudentsCsv(courseId: number): Promise<void> {
  await downloadCsv(`/et/courses/${courseId}/students.csv`, `course-${courseId}-students.csv`)
}

/** 匯出區塊 3 之問卷結果（含問答題文字答案）。 */
export async function downloadSurveyCsv(courseId: number): Promise<void> {
  await downloadCsv(`/et/courses/${courseId}/survey-result.csv`, `course-${courseId}-survey.csv`)
}
