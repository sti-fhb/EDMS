import type { SurveyAnswerRow, SurveyForm, SurveySubmitResult } from "./surveyFillSchemas"
import { http } from "../../services/http"

/** ET05 課後問卷填寫 API（US13 / #284）。 */
export const surveyFillApi = {
  form: async (courseId: number): Promise<SurveyForm> => {
    const { data } = await http.get<SurveyForm>(`/et/courses/${courseId}/survey/form`)
    return data
  },

  submit: async (courseId: number, answers: SurveyAnswerRow[]): Promise<SurveySubmitResult> => {
    const { data } = await http.post<SurveySubmitResult>(`/et/courses/${courseId}/survey/response`, { answers })
    return data
  },
}
