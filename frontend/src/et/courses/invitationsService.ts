import { http } from "../../services/http"
import type { EmailInviteResult, InviteAcceptResult, InvitePreview } from "./invitationSchemas"

/**
 * ET02 邀請學員 API（US8 / #273）。
 *
 * 預覽與寄送都是 POST：收件人清單是個資，放在 query string 會進 access log、
 * 瀏覽器歷史與 Referer。
 */
export const invitationsApi = {
  /** 邀請信預覽（唯讀；主旨與內文由管理者於平台後台統一維護）。 */
  preview: async (courseId: number, emails: string): Promise<InvitePreview> => {
    const { data } = await http.post<InvitePreview>(`/et/courses/${courseId}/invitations/preview`, { emails })
    return data
  },

  send: async (courseId: number, emails: string): Promise<EmailInviteResult> => {
    const { data } = await http.post<EmailInviteResult>(`/et/courses/${courseId}/invitations`, { emails })
    return data
  },

  /** 受邀者以邀請連結加入課程（落點頁用）。 */
  accept: async (token: string): Promise<InviteAcceptResult> => {
    const { data } = await http.post<InviteAcceptResult>("/et/invitations/accept", { token })
    return data
  },
}
