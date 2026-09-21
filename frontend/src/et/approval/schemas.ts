/** ET10 核可查詢（US17 / #385）之 API 型別。 */

/** 教師 / 管理者視角的一列（`FR-ET-US17-01`）。 */
export interface ApprovalQueryRow {
  user_id: string
  user_name: string
  course_id: number
  course_name: string
  /** `PASS` / `FAIL`。 */
  result: string
  result_note: string | null
  approved_at: string
  approved_by_name: string
  is_revoked: boolean
  revoke_reason: string | null
  revoked_by_name: string | null
  revoked_at: string | null
}

/**
 * 學員自查視角的一列（`FR-ET-US17-03`）。
 *
 * 🔴 **欄位少是規格的一部分，不是還沒寫完**：後端不回傳 `result`（恆為通過）、
 * `result_note`（教師寫的考核評語）與撤銷三件套（已撤銷者根本不在清單內）。
 * 想「補齊型別讓它跟教師視角一致」之前請先讀 `FR-ET-US17-03`。
 */
export interface MyApprovalRow {
  course_id: number
  course_name: string
  approved_at: string
}

export interface ApprovalQueryParams {
  user_name: string
  result?: "PASS" | "FAIL"
  page?: number
  limit?: number
}
