import type { TagOption } from "../courses/schemas"

/**
 * ET03 學員學習狀況追蹤（US9 / #322）之型別——對齊後端 `app/et/tracking/schemas.py`。
 *
 * ⚠️ 這是與後端共用的契約。後端有對應的 integration 測試以同一組欄位驗 schema，改這裡
 * 要一起改（同 #299 的 `CourseListParams` 慣例）。
 */

/** 完課三態，由後端**即時計算**（不讀 `ET_ENROLLMENT` 的同名死欄位）。 */
export type CompletionStatus = "NOT_STARTED" | "IN_PROGRESS" | "COMPLETED"

/**
 * 線下核可綜合狀態四態（US16 / #352），由後端以**完課狀態 × `ET_APPROVAL`** 即時衍生。
 *
 * `FR-ET-US16-02` 明訂 MUST NOT 另存狀態欄位——所以這四個值在 DB 裡不存在，
 * 每次查詢重算。前端不可自行由 `completion_status` 推導。
 */
export type ApprovalStatus = "NOT_ELIGIBLE" | "PENDING" | "PASSED" | "FAILED"

/** 核可結果二態（`ET_APPROVAL_RESULT`）。**不記考核分數**（`FR-ET-US16-04`）。 */
export type ApprovalResult = "PASS" | "FAIL"

/**
 * 批次核可時某一筆沒有寫入的理由。
 *
 * | 值 | 前端訊息 |
 * |---|---|
 * | `NOT_COMPLETED` | 單筆 `ET-MSG-ET03-304`（錯誤）/ 批次 `ET-MSG-ET03-303`（提示）|
 * | `ALREADY_APPROVED` | `ET-MSG-ET03-309` |
 * | `NOT_ENROLLED` | `ET-MSG-ET03-309` 的同形句（`ET-MSG-ET03-310`）|
 */
export type SkipReason = "NOT_COMPLETED" | "ALREADY_APPROVED" | "NOT_ENROLLED"

export interface SkippedItem {
  user_id: string
  reason: SkipReason
}

/**
 * 核可結果。
 *
 * ⚠️ **`approved === 0` 也是 HTTP 200**——全部被跳過時後端不回錯誤（單筆與批次共用
 * 同一條路徑，分兩種回應格式會讓前端對同一個動作維護兩套解析）。所以呼叫端**必須看
 * `skipped`**，不可只看 HTTP 狀態碼就報「已完成核可」。
 */
export interface ApproveResult {
  approved: number
  skipped: SkippedItem[]
}

/** 區塊 1 的一列學員。 */
export interface StudentRow {
  user_id: string
  /** 取自 `DP_USER`；帳號已刪時為 `null`（顯示「—」）。 */
  user_name: string | null
  joined_at: string
  completion_status: CompletionStatus
  /** 0~100。**完課判定不看這個值**（四捨五入會讓 201/200 變成 100）。 */
  progress_pct: number
  /**
   * 已作答測驗之最高分平均；**完全未作答時為 `null`**。
   *
   * ⚠️ 顯示「—」而**不是 0**——0 分與未作答意義相反，混為一談會讓教師誤判需要輔導的對象。
   * 後端回字串（`Decimal` 序列化）以免浮點誤差。
   */
  avg_score: string | null
  /** 最近一次學習動作**或測驗提交**（後端已取兩者較晚者）。 */
  last_activity_at: string | null
  /**
   * 是否有**作答中（未提交）**的 attempt——決定移除確認框是否用警告版文案
   * （`ET-MSG-ET03-003`）。
   *
   * ⚠️ 與上面的 `completion_status === "IN_PROGRESS"` **無關**：那是課程學習進行中
   * （由完成項目數導出），這是「手上有一份還沒交的考卷」。兩者同名不同義。
   */
  has_in_progress_attempt: boolean

  /**
   * 線下核可綜合狀態（US16）。
   *
   * 🔴 **`null` 代表該課程 `REQUIRE_APPROVAL = false`**，此時整個核可欄、勾選框與
   * 工具列都不渲染（`FR-ET-US16-02`）。不是「還沒被核可」——那是 `"PENDING"`。
   *
   * 下面四個欄位同樣在未啟用時為 `null`；`approval_status` 為 `"NOT_ELIGIBLE"` 或
   * `"PENDING"`（尚無紀錄）時它們也是 `null`。
   */
  approval_status: ApprovalStatus | null
  /** 核可備註（`RESULT_NOTE`），多用於「不通過」的原因。 */
  approval_note: string | null
  /** 核可人姓名。wireframe 的「{核可人} 核可 {日期}」小字。 */
  approved_by_name: string | null
  approved_at: string | null
  /** 樂觀鎖版本——撤銷時**原樣帶回**，不可自行遞增或省略。 */
  approval_version: number | null
}

/** 區塊 2：某學員於某測驗的一次作答。 */
export interface TeacherAttemptRow {
  attempt_id: number
  attempt_no: number
  submitted_at: string
  score: string
  /** 該次配分總和（快照）。**分母用它、不可寫死 100**——發布後教師仍可改配分。 */
  points_total: number
  is_pass: boolean
}

/** 區塊 2：某學員於某測驗的概況。 */
export interface TeacherQuizRow {
  quiz_id: number
  quiz_name: string
  max_retry: number
  /** 本輪已用次數（已扣掉重置基準）。 */
  used_attempts: number
  is_passed: boolean
  /**
   * 是否可重置重考次數——**由後端判定，前端不自行推導**。
   *
   * 規則是「次數用盡且未及格且曾作答」，其中「用盡」是 `used > max_retry`（總配額為
   * `max_retry + 1`）。在前端複製一份遲早與後端分岔。
   */
  can_reset: boolean
  /** 空陣列代表**尚未作答**（ET-MSG-ET03-005）——該測驗仍要列出。 */
  attempts: TeacherAttemptRow[]
}

export interface TeacherStudentAttempts {
  user_id: string
  user_name: string | null
  quizzes: TeacherQuizRow[]
}

/** 區塊 2 的完整回應（不分頁——規格明訂一次列出所有曾作答之學員）。 */
export interface AttemptOverview {
  students: TeacherStudentAttempts[]
}

/**
 * 逐題明細的一個選項。
 *
 * 🔴 **欄位名以後端 `app/et/attempt/schemas.py::OptionResult` 為準**：`text` / `selected`，
 * **不是** `option_text` / `is_selected`。本檔其餘型別多用 `xxx_text` 風格，但這一個不行
 * ——它是後端回應的原樣，而那個 schema 由學員端與教師端**兩個端點共用**
 * （`attempt/service.py::to_question_result`），改後端等於動到已交付的學員端 API。
 *
 * ⚠️ 這裡曾經抄錯過（#358）：型別是 TypeScript `interface`、只存在於編譯期，執行期讀到
 * `undefined` 不會爆——選項文字變空白、`selected` 為 falsy 故每題都標成未選，**連滿分的
 * 題目都顯示「（正確答案，未選）」**，而且不報錯、CI 全綠。
 *
 * 依 `sti-zod-conventions.md`，API 回應型別**保留手寫 interface**（zod 只用於表單），
 * 所以防護不是執行期驗證，而是後端 `test_attempt_option_result_contract.py` 釘住欄位名 +
 * 前端 fixture 以後端名字撰寫 + 一條真的渲染選項的測試。
 */
export interface OptionResult {
  option_id: number
  text: string
  is_correct: boolean
  selected: boolean
}

/** 逐題明細的一題。 */
export interface QuestionResult {
  question_id: number
  question_type: string
  stem: string
  points: string
  score: string
  outcome: "CORRECT" | "PARTIAL" | "WRONG"
  options: OptionResult[]
}

/** 區塊 2：教師端單次 attempt 之逐題明細。 */
export interface TeacherAttemptDetail {
  attempt_id: number
  user_id: string
  user_name: string | null
  quiz_name: string
  attempt_no: number
  submitted_at: string
  score: string
  points_total: number
  pass_score: number
  is_pass: boolean
  questions: QuestionResult[]
}

/** 區塊 3：統計檢視的一個選項。 */
export interface SurveyOptionStat {
  so_id: number
  option_text: string
  count: number
}

/** 區塊 3：統計檢視的一題。 */
export interface SurveyQuestionStat {
  sq_id: number
  stem: string
  question_type: string
  /** 已作答此題的人數。**問答題唯一的統計值**。 */
  answered_count: number
  /** 單選題的選項分布；**問答題恆為空陣列**（2026-08-28 裁示：文字屬明細檢視）。 */
  options: SurveyOptionStat[]
}

export interface SurveyDetailAnswer {
  sq_id: number
  option_text: string | null
  answer_text: string | null
}

export interface SurveyDetailRow {
  user_id: string
  user_name: string | null
  submitted_at: string
  answers: SurveyDetailAnswer[]
}

/**
 * 區塊 3 的完整回應。
 *
 * `has_survey === false` 時**整個區塊不渲染**（`FR-ET-US9-07` 明訂隱藏）——不是顯示空
 * 狀態。後端刻意不回 404，否則前端分不出「這門課沒問卷」與「你沒權限」。
 */
export interface SurveyResult {
  has_survey: boolean
  survey_name: string | null
  filled_count: number
  /** 未填人數；母體為**在籍**學員（已移除者不計入）。 */
  not_filled_count: number
  questions: SurveyQuestionStat[]
  details: SurveyDetailRow[]
}

/** 課程下拉的一個選項（取自 ET01 的課程清單）。 */
export interface CourseOption {
  course_id: number
  course_name: string
  is_closed: boolean
  tags: TagOption[]
}

/**
 * 原有 `PendingInviteRow`（ET-12「待加入」分頁的一列）已隨 #362 移除。
 *
 * ⚠️ 不要把 `ApprovalStatus` 的 `"PENDING"` 誤認為它的遺留——那是**核可**尚未裁定，
 * 與已廢除的邀請狀態無關。
 */
