import type { TagOption } from "../courses/schemas"

/**
 * ET03 學員學習狀況追蹤（US9 / #322）之型別——對齊後端 `app/et/tracking/schemas.py`。
 *
 * ⚠️ 這是與後端共用的契約。後端有對應的 integration 測試以同一組欄位驗 schema，改這裡
 * 要一起改（同 #299 的 `CourseListParams` 慣例）。
 */

/** 完課三態，由後端**即時計算**（不讀 `ET_ENROLLMENT` 的同名死欄位）。 */
export type CompletionStatus = "NOT_STARTED" | "IN_PROGRESS" | "COMPLETED"

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

/** 逐題明細的一個選項（沿用學員端 `OptionResult` 形狀）。 */
export interface OptionResult {
  option_id: number
  option_text: string
  is_correct: boolean
  is_selected: boolean
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
 * ET-12「待加入」分頁的一列（`FR-ET-US12-01`）。
 *
 * `status` 恆為 `"PENDING"`——清單已於後端過濾。仍回傳是因為 spec 明訂欄位須含邀請
 * 狀態，且日後清單擴及其他狀態時不必改結構。
 */
export interface PendingInviteRow {
  invitation_id: number
  email: string
  /**
   * **最後**寄送時間，不是首次。
   *
   * 教師按「再次寄送」後若畫面日期不變，他會以為沒寄出去而重複點——所以顯示的是
   * `LAST_SENT_AT`。
   */
  last_sent_at: string
  status: string
}
