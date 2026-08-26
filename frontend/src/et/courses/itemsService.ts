import { http } from "../../services/http"
import type {
  DmDocOption,
  ItemRow,
  ItemType,
  MaterialDetail,
  QuestionRow,
  QuestionType,
  QuizDetail,
  VideoRow,
} from "./itemSchemas"

/** 章節項目 API（US3 / #203）。 */
export const itemsApi = {
  /** 新增項目——後端於同一交易內一併建立對應之教材 / 測驗空殼。 */
  add: async (chapterId: number, itemType: ItemType, title: string): Promise<ItemRow> => {
    const { data } = await http.post<ItemRow>(`/et/chapters/${chapterId}/items`, {
      item_type: itemType,
      title,
    })
    return data
  },

  /** 重排送**完整順序陣列**；`version` 為**章節層**版本。 */
  reorder: async (chapterId: number, itemIds: number[], version: number): Promise<void> => {
    await http.put(`/et/chapters/${chapterId}/items/order`, { item_ids: itemIds, version })
  },

  remove: async (itemId: number): Promise<void> => {
    await http.delete(`/et/items/${itemId}`)
  },
}

/** 教材內容 API（US3 / #203）。 */
export const materialsApi = {
  getDetail: async (materialId: number): Promise<MaterialDetail> => {
    const { data } = await http.get<MaterialDetail>(`/et/materials/${materialId}`)
    return data
  },

  /**
   * 更新教材——送**最終狀態**（名稱、說明、文件集合、要保留的影片），全量覆寫。
   *
   * 文件引用原本是逐筆即時端點，2026-08-26 改為隨儲存一次套用：逐筆即時會讓
   * 「取消」失去意義，也讓「至少擇一媒材」的檢核被繞過。
   */
  update: async (
    materialId: number,
    payload: {
      material_name: string
      description_html: string | null
      doc_ids: string[]
      video_ids: number[]
      version: number
    },
  ): Promise<void> => {
    await http.put(`/et/materials/${materialId}`, payload)
  },

  /**
   * 上傳影片（multipart）。
   *
   * 不設 `Content-Type`——瀏覽器會自行帶上含 boundary 的 `multipart/form-data`，
   * 手動指定反而會少掉 boundary 讓後端解析失敗。
   */
  uploadVideo: async (materialId: number, file: File): Promise<VideoRow> => {
    const form = new FormData()
    form.append("file", file)
    const { data } = await http.post<VideoRow>(`/et/materials/${materialId}/videos`, form)
    return data
  },

  /** DM 訓練教材下拉（SRVDM002）——已排除廢止文件，但保留「廢止待簽核」者。 */
  listDmDocuments: async (keyword = ""): Promise<DmDocOption[]> => {
    const { data } = await http.get<DmDocOption[]>("/et/dm-documents", {
      params: keyword ? { keyword } : undefined,
    })
    return data
  },

}

interface QuestionPayload {
  question_type: QuestionType
  stem: string
  points: number
  options: { option_text: string; is_correct: boolean }[]
}

/** 測驗設定與題目 API（US3 / #203）。 */
export const quizzesApi = {
  getDetail: async (quizId: number): Promise<QuizDetail> => {
    const { data } = await http.get<QuizDetail>(`/et/quizzes/${quizId}`)
    return data
  },

  update: async (
    quizId: number,
    payload: {
      quiz_name: string
      description: string | null
      pass_score: number
      time_limit_min: number | null
      max_retry: number
      version: number
    },
  ): Promise<void> => {
    await http.put(`/et/quizzes/${quizId}`, payload)
  },

  addQuestion: async (quizId: number, payload: QuestionPayload): Promise<QuestionRow> => {
    const { data } = await http.post<QuestionRow>(`/et/quizzes/${quizId}/questions`, payload)
    return data
  },

  /** 選項為**全量覆寫**（後端把舊選項軟刪、插入新的）。 */
  updateQuestion: async (
    questionId: number,
    payload: QuestionPayload & { version: number },
  ): Promise<void> => {
    await http.put(`/et/questions/${questionId}`, payload)
  },

  removeQuestion: async (questionId: number): Promise<void> => {
    await http.delete(`/et/questions/${questionId}`)
  },

  /** 題目重排（教師端呈現順序）；`version` 為**測驗層**版本。 */
  reorderQuestions: async (quizId: number, questionIds: number[], version: number): Promise<void> => {
    await http.put(`/et/quizzes/${quizId}/questions/order`, { question_ids: questionIds, version })
  },
}
