import { http } from "../../services/http"
import type { AttemptResult, AttemptState, QuizIntro } from "./attemptSchemas"

/** ET06 測驗作答 API（US6 / #279）。 */
export const attemptApi = {
  intro: async (quizId: number): Promise<QuizIntro> => {
    const { data } = await http.get<QuizIntro>(`/et/quizzes/${quizId}/intro`)
    return data
  },

  /**
   * 開始作答。**已有未完成的作答時回既有那一筆**（`resumed: true`），不建新的、不吃次數。
   *
   * 故本呼叫是「開始或繼續」——前端不需要（也不該）自己判斷該建新的還是續作，
   * 那個判定在後端，兩邊各判一次遲早會分岔。
   */
  start: async (quizId: number): Promise<AttemptState> => {
    const { data } = await http.post<AttemptState>(`/et/quizzes/${quizId}/attempts`)
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
}
