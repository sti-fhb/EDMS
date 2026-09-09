/** ET06 測驗作答型別（對齊後端 `app/et/attempt/schemas.py`）。 */

/**
 * 作答中的選項——**沒有 `is_correct`**。
 *
 * 正確答案只在提交後的 `OptionResult` 才會出現。兩個型別刻意分開而非共用基底：
 * 共用之後只要有人為了少寫幾行把 `is_correct` 提到共同欄位，作答中就會跟著漏出去，
 * 而畫面上完全看不出來。
 */
export interface OptionForAnswering {
  option_id: number
  text: string
}

export interface QuestionForAnswering {
  question_id: number
  question_type: "SINGLE" | "MULTIPLE"
  stem: string
  points: number
  options: OptionForAnswering[]
  /** 已暫存的作答；空陣列 = 未作答（供導覽列的「已答 / 未答」三態）。 */
  selected_options: number[]
}

export interface AttemptState {
  attempt_id: number
  quiz_id: number
  quiz_name: string
  attempt_no: number
  /** 目前狀態；非 `IN_PROGRESS` 時前端不再渲染作答畫面。 */
  status: "IN_PROGRESS" | "SUBMITTED" | "TIMEOUT"
  pass_score: number
  time_limit_min: number | null
  /**
   * 剩餘秒數，由後端自 `STARTED_AT` 推導。**`null` = 不限時**——不可當成 0
   *（那會渲染成「時間到」並立刻自動提交）。
   */
  remaining_sec: number | null
  /** 回傳的是既有的進行中作答而非新建（SA 裁示 Q1 = A）。 */
  resumed: boolean
  questions: QuestionForAnswering[]
}

/** 明細中的選項：**此時才帶正確答案**（AC 11 強制顯示）。 */
export interface OptionResult {
  option_id: number
  text: string
  is_correct: boolean
  selected: boolean
}

export interface QuestionResult {
  question_id: number
  question_type: "SINGLE" | "MULTIPLE"
  stem: string
  points: number
  score: string
  /** `CORRECT` / `PARTIAL` / `WRONG`——由後端判定，前端不自行由得分推導。 */
  outcome: "CORRECT" | "PARTIAL" | "WRONG"
  options: OptionResult[]
}

export interface AttemptResult {
  attempt_id: number
  /** `attempt_id` 與 `quiz_id` 是兩個獨立的序列，不可互推。 */
  quiz_id: number
  /** 供導回該課程的學習頁——重考的入口（測驗面板）在那裡。 */
  course_id: number
  attempt_no: number
  status: "SUBMITTED" | "TIMEOUT"
  score: string
  /** 本次的配分總和。**分母用它、不可寫死 100**——發布後教師仍可改配分或增刪題目。 */
  points_total: number
  pass_score: number
  is_pass: boolean
  submitted_at: string
  remaining_attempts: number
  /** 課程是否已關閉——成績頁據以顯示 ET-MSG-ET06-005（#280 裁示 Q3 = B：事後告知）。 */
  course_closed: boolean
  questions: QuestionResult[]
}

/**
 * 歷次作答清單的一列（#280 AC 1）。
 *
 * **只含已閱卷的 attempt**——進行中的還沒有成績；「繼續作答」由
 * `QuizIntro.in_progress_attempt_id` 負責，不在這份清單裡。
 */
export interface AttemptSummary {
  attempt_id: number
  attempt_no: number
  submitted_at: string
  score: string
  /** 該次的配分總和。**不可省略分母**——發布後教師仍可改配分，60/100 與 60/300 在
   * 清單上都只顯示「60」時，「結業成績以最高分為準」那句話就變成誤導。 */
  points_total: number
  is_pass: boolean
  status: "SUBMITTED" | "TIMEOUT"
}

/**
 * 提交後導向結果頁時帶的 router state。
 *
 * `left_window` 是**前端自己知道的事**（後端只看到一次普通提交），故不放進 `AttemptResult`
 * ——那個型別對齊後端 schema，混進純前端欄位會讓人以為 API 有回傳它。
 */
export interface ResultNavState extends AttemptResult {
  /** 本次提交由「離開作答視窗」觸發，非學員主動按提交。 */
  left_window?: boolean
}

export interface QuizIntro {
  quiz_id: number
  quiz_name: string
  description: string | null
  question_count: number
  pass_score: number
  /** `null` = 不限時。前端須顯示「不限時」而**不是「0 分」**。 */
  time_limit_min: number | null
  max_retry: number
  remaining_attempts: number
  can_start: boolean
  /** 最近一次成績。與 `best_score` 並列——結業成績取最高分，只顯示其一都會誤導。 */
  last_score: string | null
  best_score: string | null
  is_passed: boolean
  /** 有未完成的作答時帶其 id，按鈕改為「繼續作答」。 */
  in_progress_attempt_id: number | null
  /**
   * 最近一次**已提交**的 attempt；`null` = 從未作答完成。
   *
   * 供「查看上次作答明細」。此入口**不受 `can_start` 影響**——次數用完的學員正是最需要
   * 回頭看錯在哪的人，把複習跟著作答一起關掉等於懲罰他考不好。
   */
  last_attempt_id: number | null
  /**
   * 課程是否已關閉。
   *
   * ⚠️ **`can_start === false` 有兩種成因**（次數用完、課程關閉），對學員的意義相反：
   * 前者聯繫教師重置有用，後者重置一點用也沒有。少了這個欄位就只能寫死一句「重考次數
   * 已用完，請聯繫教師重置」，而那會叫課程關閉的學員去做一件沒有用的事。
   */
  course_closed: boolean
}

/** 導覽列的題目狀態。 */
export type QuestionNavState = "answered" | "current" | "unanswered"

export function questionNavState(
  question: QuestionForAnswering,
  currentQuestionId: number | null,
): QuestionNavState {
  if (question.question_id === currentQuestionId) return "current"
  return question.selected_options.length > 0 ? "answered" : "unanswered"
}

/** 倒數顯示格式 `MM:SS`；小時以上仍以分鐘累計（`90:00` 而非 `1:30:00`）。 */
export function formatCountdown(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(safe / 60)
  const seconds = safe % 60
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
}
