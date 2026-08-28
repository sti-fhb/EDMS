import { http } from "../../services/http"
import type {
  PublishCheckResult,
  PublishResult,
  SurveyDetail,
  SurveyQuestionFormValues,
  SurveyQuestionRow,
} from "./surveySchemas"

/** ET02 課後問卷 API（US3 / #204）。 */
export const surveyApi = {
  /**
   * 課程之問卷；**尚未建立時後端回 `null`（200）而非 404**。
   *
   * 問卷為選配（AC 23），「沒有」是正常狀態——回 404 會被 `toApiError` 當成故障，
   * 每個沒建問卷的課程都會跳一次錯誤。
   */
  get: async (courseId: number): Promise<SurveyDetail | null> => {
    const { data } = await http.get<SurveyDetail | null>(`/et/courses/${courseId}/survey`)
    return data
  },

  create: async (courseId: number, surveyName: string): Promise<SurveyDetail> => {
    const { data } = await http.post<SurveyDetail>(`/et/courses/${courseId}/survey`, { survey_name: surveyName })
    return data
  },

  /** 更新名稱與啟用狀態。**凍結後仍可呼叫**——停用問卷走的正是這條（AC 21）。 */
  update: async (
    surveyId: number,
    payload: { survey_name: string; is_active: boolean; version: number },
  ): Promise<void> => {
    await http.put(`/et/surveys/${surveyId}`, payload)
  },

  addQuestion: async (surveyId: number, values: SurveyQuestionFormValues): Promise<SurveyQuestionRow> => {
    const { data } = await http.post<SurveyQuestionRow>(`/et/surveys/${surveyId}/questions`, values)
    return data
  },

  updateQuestion: async (sqId: number, payload: SurveyQuestionFormValues & { version: number }): Promise<void> => {
    await http.put(`/et/survey-questions/${sqId}`, payload)
  },

  deleteQuestion: async (sqId: number): Promise<void> => {
    await http.delete(`/et/survey-questions/${sqId}`)
  },

  /** 重排送**完整順序陣列**，version 為**問卷層**版本。 */
  reorderQuestions: async (surveyId: number, questionIds: number[], version: number): Promise<void> => {
    await http.put(`/et/surveys/${surveyId}/questions/order`, { question_ids: questionIds, version })
  },
}

/** ET02 課程發布 API（US3 / #204）。 */
export const publishApi = {
  /** 預檢：回缺漏清單、不改狀態。發布端點自身仍會重驗，這裡只是體驗。 */
  check: async (courseId: number): Promise<PublishCheckResult> => {
    const { data } = await http.get<PublishCheckResult>(`/et/courses/${courseId}/publish-check`)
    return data
  },

  publish: async (courseId: number): Promise<PublishResult> => {
    const { data } = await http.post<PublishResult>(`/et/courses/${courseId}/publish`)
    return data
  },
}
