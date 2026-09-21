import { http } from "../../services/http"
import type { ApprovalQueryParams, ApprovalQueryRow, MyApprovalRow } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"

/**
 * ET10 核可查詢 API（US17 / #385）——**唯讀**，不含任何核可 / 撤銷動作（那些在 US16）。
 *
 * 兩支端點**刻意分開**而非同一支加參數：授權模型、回應欄位與資料範圍三者都不同。
 * `mine` 不帶任何識別參數——對象由後端從 token 取得，前端沒有可傳錯的東西。
 */
export const approvalsApi = {
  /** 教師 / 管理者依學員姓名查詢。可見範圍由後端依 SA Q1 裁示 C 分流。 */
  search: async (params: ApprovalQueryParams): Promise<PagedResult<ApprovalQueryRow>> => {
    const { data } = await http.get<PagedResult<ApprovalQueryRow>>("/et/approvals", { params })
    return data
  },

  /** 學員自查：自己已通過（有效未撤銷）的課程。 */
  mine: async (params: { page?: number; limit?: number }): Promise<PagedResult<MyApprovalRow>> => {
    const { data } = await http.get<PagedResult<MyApprovalRow>>("/et/approvals/mine", { params })
    return data
  },
}
