import { http } from "../../services/http"
import type { JoinPreview, JoinResult, MyCoursesResult } from "./myCoursesSchemas"

/** ET04 我的課程與加入新課程 API（US4 / #247）。 */
export const myCoursesApi = {
  list: async (): Promise<MyCoursesResult> => {
    const { data } = await http.get<MyCoursesResult>("/et/my-courses")
    return data
  },

  /**
   * 驗證邀請碼並取課程資訊，**不寫入**（AC 6）。
   *
   * 以 POST 送出而非 query string：邀請碼是憑證，放在 URL 會進 access log、
   * 瀏覽器歷史與 Referer。
   */
  preview: async (invitationCode: string): Promise<JoinPreview> => {
    const { data } = await http.post<JoinPreview>("/et/enrollments/preview", { invitation_code: invitationCode })
    return data
  },

  join: async (invitationCode: string): Promise<JoinResult> => {
    const { data } = await http.post<JoinResult>("/et/enrollments", { invitation_code: invitationCode })
    return data
  },
}
