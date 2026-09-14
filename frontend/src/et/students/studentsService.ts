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
    await http.post(`/et/courses/${courseId}/students/${userId}/quizzes/${quizId}/retry-reset`)
  },

  /** 移除學員（軟刪；學習歷史保留）。 */
  removeStudent: async (courseId: number, userId: string): Promise<void> => {
    await http.delete(`/et/courses/${courseId}/students/${userId}`)
  },
}

/**
 * 兩支 CSV 匯出的相對路徑。
 *
 * **不用 axios 取回再組 Blob**——那樣要自行處理 `Content-Disposition` 與記憶體，而瀏覽器
 * 原生就會依該標頭下載。由呼叫端組出完整 URL 後開新視窗即可。
 */
export const studentsCsvPaths = {
  students: (courseId: number) => `/api/et/courses/${courseId}/students.csv`,
  survey: (courseId: number) => `/api/et/courses/${courseId}/survey-result.csv`,
}
