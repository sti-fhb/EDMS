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
   * 學員**姓名或 Email**，擇一命中即可（#436）。
   *
   * ⚠️ **三者的比對語意不同**（#456）：姓名為部分比對；Email 僅 `@` 之前做部分比對；
   * 完整 Email 做相等比對。查詢 `@sti.com.tw` 這類網域字串**不會有任何結果**——那是
   * 刻意的，全體共享同一網域，比對它只會得到「全部人」或「沒有人」。
   *
   * **選填**。↔️ #548 之前與 `course_id`「至少給一個」，兩者皆不給回 422
   * `ET_APPROVAL_006`；裁示 3 之後留白查詢是合法操作（承重轉到讀取稽核）。
   */
  keyword?: string
  /**
   * 課程篩選（#439）。↔️ #548 裁示 4 之前非管理者只能給自己開設的課程（403
   * `ET_APPROVAL_007`）；現在不分 owner，下拉也列出所有有核可紀錄的課程。
   */
  course_id?: number
  /** 核可結果，對應 `ET_APPROVAL.RESULT`。 */
  result?: "PASS" | "FAIL"
  /**
   * 撤銷狀態，對應 `ET_APPROVAL.IS_REVOKED`。
   *
   * 🔴 **與 `result` 正交，⛔ 不可合併成一個欄位**（#548 裁示 6）。被撤銷的紀錄其
   * `RESULT` 仍是 `PASS` 或 `FAIL`——兩者從來不是同一個欄位的不同值。把「已撤銷」
   * 併進 `result` 正是改制前那個缺陷的成因：「僅通過」只比對 `RESULT`，於是會列出
   * 已撤銷的通過。
   *
   * 畫面上仍是**單一下拉**，由 `RESULT_OPTIONS` 映射成這一對值。
   */
  revoked?: boolean
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
