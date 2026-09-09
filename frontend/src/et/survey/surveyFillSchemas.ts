/** ET05 課後問卷填寫型別與純函式（US13 / #284；對齊後端 `app/et/survey_fill/schemas.py`）。 */

/** 問卷題型（對齊後端 `ET_SURVEY_QUESTION_TYPE`）。 */
export type SurveyQuestionType = "SINGLE" | "TEXT"

/**
 * 入口 / 頁面狀態（對齊後端 `survey_fill/rules.py` 之 `ENTRY_*`）。
 *
 * 以**單一狀態值**分支，不用布林旗標的組合——那會產生不可能的狀態（如「已送出且未
 * 完課且問卷已停用」該顯示什麼？），且每種組合都得寫一條分支。
 */
export type SurveyEntryState = "HIDDEN" | "FILLABLE" | "SUBMITTED" | "COURSE_CLOSED"

/** 文字答案上限（後端 `ANSWER_TEXT_MAX_LEN`，對應 `VARCHAR(150)`）。 */
export const ANSWER_TEXT_MAX_LEN = 150

export interface SurveyEntry {
  survey_id: number
  survey_name: string
  state: SurveyEntryState
  /** 自己的送出時間；`state !== "SUBMITTED"` 時為 null。 */
  submitted_at: string | null
}

export interface SurveyOptionRow {
  so_id: number
  option_text: string
}

export interface SurveyQuestionRow {
  sq_id: number
  question_type: SurveyQuestionType
  stem: string
  /** 問答題恆為空陣列（後端 `ET_SURVEY_008`：問答題不可設定選項）。 */
  options: SurveyOptionRow[]
}

export interface SurveyAnswerRow {
  sq_id: number
  so_id: number | null
  answer_text: string | null
}

export interface SurveyForm {
  survey_id: number
  survey_name: string
  state: SurveyEntryState
  submitted_at: string | null
  questions: SurveyQuestionRow[]
  /** **留空的問答題不會出現在此清單**——後端 `_D` 只記錄實際有作答的題目。 */
  my_answers: SurveyAnswerRow[]
}

export interface SurveySubmitResult {
  response_id: number
  submitted_at: string
}

/** 作答草稿：單選存 `so_id`、問答存文字。以 `sq_id` 為鍵。 */
export type AnswerDraft = Record<number, { so_id?: number; answer_text?: string }>

/**
 * 尚未作答的**單選題** `sq_id`。
 *
 * ⚠️ **問答題不列入**（FR-ET-US13-03：問答題為選填，留空 MUST NOT 阻擋送出）。
 * issue body 驗收條件 3 寫「全部題目作答後方可送出」，那是 #238 加入問答題之前的
 * 敘述——以 spec 為準。
 */
export function unansweredSingleIds(questions: SurveyQuestionRow[], draft: AnswerDraft): number[] {
  return questions
    .filter((q) => q.question_type === "SINGLE" && draft[q.sq_id]?.so_id === undefined)
    .map((q) => q.sq_id)
}

/**
 * 草稿 → 送出用的作答清單。
 *
 * **留空（或只打空白）的問答題整筆略過**——與後端 `build_detail_rows` 同一個判定
 * （SA Q1 裁示 A：`_D` 只記錄實際有作答的題目，使「表裡有列 ⇔ 學員答了這題」成立）。
 * 前端一併過濾不是為了正確性（後端會再判一次），而是不讓請求帶著一堆空字串。
 */
export function toAnswerPayload(questions: SurveyQuestionRow[], draft: AnswerDraft): SurveyAnswerRow[] {
  const payload: SurveyAnswerRow[] = []
  for (const question of questions) {
    const answer = draft[question.sq_id]
    if (answer === undefined) continue
    if (question.question_type === "SINGLE") {
      if (answer.so_id === undefined) continue
      payload.push({ sq_id: question.sq_id, so_id: answer.so_id, answer_text: null })
      continue
    }
    const text = (answer.answer_text ?? "").trim()
    if (text === "") continue
    payload.push({ sq_id: question.sq_id, so_id: null, answer_text: text })
  }
  return payload
}

/**
 * 已送出之填答 → 草稿（唯讀回看時據此顯示選中的選項與文字）。
 *
 * 沒有出現在 `my_answers` 的題目就是**當時留空的問答題**，草稿裡不會有它的鍵，
 * 前端據此呈現為「未填」。
 */
export function draftFromAnswers(answers: SurveyAnswerRow[]): AnswerDraft {
  const draft: AnswerDraft = {}
  for (const answer of answers) {
    draft[answer.sq_id] = {
      so_id: answer.so_id ?? undefined,
      answer_text: answer.answer_text ?? undefined,
    }
  }
  return draft
}

/** 是否為唯讀呈現（已送出、或課程已關閉而未填）。 */
export function isReadOnly(state: SurveyEntryState): boolean {
  return state !== "FILLABLE"
}
