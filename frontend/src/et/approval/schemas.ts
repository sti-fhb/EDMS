/** ET04 核可查詢（US17 / #385）之 API 型別。 */

/** 教師 / 管理者視角的一列（`FR-ET-US17-01`）。 */
export interface ApprovalQueryRow {
  user_id: string
  user_name: string
  course_id: number
  course_name: string
  /** `PASS` / `FAIL`。 */
  result: string
  result_note: string | null
  /**
   * 通過時間——核可列為核可時間，完課列為第一次完課的時間（#464）。
   *
   * ⚠️ 可為 `null`：活化前就已完課的既有資料。後端以 `NULLS LAST` 排在最後。
   */
  approved_at: string | null
  /**
   * ⚠️ 可為 `null`：不需線下核可的課程**事實上沒有核可者**（#464）——不是遮蔽、也不是忘了填。
   */
  approved_by_name: string | null
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
  /** 通過時間（#464 起含不需核可課程的完課時間）；活化前的既有完課可為 `null`。 */
  approved_at: string | null
}

export interface ApprovalQueryParams {
  /**
   * 學員**姓名或 Email**（皆為部分比對，擇一命中即可，#436）。
   *
   * **選填**（#439）——與 `course_id`「至少給一個」，兩者皆不給後端回 422
   * `ET_APPROVAL_006`。⛔ 不要為了型別方便改回必填：只給課程的查詢正是本次要加的用法。
   */
  keyword?: string
  /**
   * 課程篩選（#439）。
   *
   * 🔴 非管理者**只能給自己開設的課程**，否則後端回 403 `ET_APPROVAL_007`。
   * 下拉本來就只列得出自己的課，那道閘擋的是直接送出的請求。
   */
  course_id?: number
  result?: "PASS" | "FAIL"
  page?: number
  limit?: number
}

/**
 * ET04 課程篩選下拉的一個選項（#439）。
 *
 * ⚠️ 母體是**有核可紀錄的課程**，不是 ET01 的課程清單——後者的 `scope=all` 排除了
 * 已結束的課程，而核可紀錄絕大多數正落在那些課上。細節見後端 `ApprovalCourseOption`。
 */
export interface ApprovalCourseOption {
  course_id: number
  course_name: string
}
