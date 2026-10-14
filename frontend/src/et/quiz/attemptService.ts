import { http } from "../../services/http"
import type { AttemptResult, AttemptState, AttemptSummary, QuizIntro, QuizPreview } from "./attemptSchemas"

/** ET07 測驗作答 API（US6 / #279、#280）。 */
export const attemptApi = {
  intro: async (quizId: number): Promise<QuizIntro> => {
    const { data } = await http.get<QuizIntro>(`/et/quizzes/${quizId}/intro`)
    return data
  },

  /**
   * 教師預覽用的**唯讀**題目清單（#486）。
   *
   * ⚠️ **在籍學員呼叫會 404**——他要看題目只有「開始作答」一條路。故呼叫端必須先確認
   * `intro.is_preview`，不可無條件查。
   */
  preview: async (quizId: number): Promise<QuizPreview> => {
    const { data } = await http.get<QuizPreview>(`/et/quizzes/${quizId}/preview`)
    return data
  },

  /**
   * 歷次作答清單（**每一次**，不限最近一次）。
   *
   * 課程關閉後與被移除的學員**仍讀得到**——後端的授權只看 `USER_ID`，不問課程資格。
   */
  history: async (quizId: number): Promise<AttemptSummary[]> => {
    const { data } = await http.get<AttemptSummary[]>(`/et/quizzes/${quizId}/attempts`)
    return data
  },

  /**
   * 開始作答。**已有未完成的作答時，後端以已暫存的作答結算那一筆並回成績**（`AttemptResult`，
   * #640；原為續作），不建新的。以 `isSettled` 分流：作答狀態 → 進作答頁；成績 → 進結果頁。
   *
   * 該建新的還是結算由後端判定——前端不自己判斷，兩邊各判一次遲早會分岔。
   */
  start: async (quizId: number): Promise<AttemptState | AttemptResult> => {
    const { data } = await http.post<AttemptState | AttemptResult>(`/et/quizzes/${quizId}/attempts`)
    return data
  },

  state: async (attemptId: number): Promise<AttemptState> => {
    const { data } = await http.get<AttemptState>(`/et/attempts/${attemptId}`)
    return data
  },

  /** 暫存單題作答（切換題目時觸發）。空陣列為合法輸入——學員可以取消勾選。 */
  saveAnswer: async (attemptId: number, questionId: number, selected: number[]): Promise<void> => {
    await http.put(`/et/attempts/${attemptId}/answers/${questionId}`, { selected_options: selected })
  },

  submit: async (attemptId: number): Promise<AttemptResult> => {
    const { data } = await http.post<AttemptResult>(`/et/attempts/${attemptId}/submit`)
    return data
  },

  /**
   * 取**已提交** attempt 的成績明細（複習用）。與 `submit` 回傳同一個型別——同一份成績單，
   * 差別只在取得時機，若兩邊型別分家，明細頁就得為兩種來源各寫一套渲染。
   */
  result: async (attemptId: number): Promise<AttemptResult> => {
    const { data } = await http.get<AttemptResult>(`/et/attempts/${attemptId}/result`)
    return data
  },
}
