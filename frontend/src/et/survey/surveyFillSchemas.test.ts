import { describe, expect, it } from "vitest"

import {
  draftFromAnswers,
  isReadOnly,
  toAnswerPayload,
  unansweredSingleIds,
} from "./surveyFillSchemas"
import type { AnswerDraft, SurveyQuestionRow } from "./surveyFillSchemas"

const SINGLE_1: SurveyQuestionRow = {
  sq_id: 1,
  question_type: "SINGLE",
  stem: "整體而言，您對本課程的內容安排是否滿意？",
  options: [
    { so_id: 11, option_text: "滿意" },
    { so_id: 12, option_text: "普通" },
  ],
}
const SINGLE_2: SurveyQuestionRow = {
  sq_id: 2,
  question_type: "SINGLE",
  stem: "影片教材的清晰度與長度是否適當？",
  options: [
    { so_id: 21, option_text: "適當" },
    { so_id: 22, option_text: "需改進" },
  ],
}
const TEXT: SurveyQuestionRow = { sq_id: 3, question_type: "TEXT", stem: "其他建議", options: [] }
const QUESTIONS = [SINGLE_1, SINGLE_2, TEXT]

describe("unansweredSingleIds", () => {
  it("回尚未選取的單選題", () => {
    expect(unansweredSingleIds(QUESTIONS, { 1: { so_id: 11 } })).toEqual([2])
  })

  it("問答題留空不列入未答", () => {
    // FR-ET-US13-03：問答題為選填，留空 MUST NOT 阻擋送出。
    // ⚠️ issue body 驗收條件 3 寫「全部題目作答後方可送出」，那是加入問答題前的敘述。
    const draft: AnswerDraft = { 1: { so_id: 11 }, 2: { so_id: 21 } }
    expect(unansweredSingleIds(QUESTIONS, draft)).toEqual([])
  })

  it("全部未答時回全部單選題", () => {
    expect(unansweredSingleIds(QUESTIONS, {})).toEqual([1, 2])
  })

  it("只有問答題的問卷永遠沒有未答題", () => {
    expect(unansweredSingleIds([TEXT], {})).toEqual([])
  })
})

describe("toAnswerPayload", () => {
  it("單選帶 so_id、文字欄為 null", () => {
    expect(toAnswerPayload([SINGLE_1], { 1: { so_id: 12 } })).toEqual([
      { sq_id: 1, so_id: 12, answer_text: null },
    ])
  })

  it("問答帶去除前後空白的文字、選項欄為 null", () => {
    expect(toAnswerPayload([TEXT], { 3: { answer_text: "  影片可以再短一些 " } })).toEqual([
      { sq_id: 3, so_id: null, answer_text: "影片可以再短一些" },
    ])
  })

  it("留空的問答題整筆略過", () => {
    // 與後端 `build_detail_rows` 同一判定（SA Q1 裁示 A：`_D` 只記錄實際有作答的題目）。
    // 前端一併過濾不是為了正確性（後端會再判一次），而是不讓請求帶著一堆空字串。
    expect(toAnswerPayload(QUESTIONS, { 1: { so_id: 11 }, 2: { so_id: 21 }, 3: { answer_text: "" } })).toEqual([
      { sq_id: 1, so_id: 11, answer_text: null },
      { sq_id: 2, so_id: 21, answer_text: null },
    ])
  })

  it("只打空白的問答題視為留空", () => {
    expect(toAnswerPayload([TEXT], { 3: { answer_text: " \t " } })).toEqual([])
  })

  it("依題目順序而非草稿鍵的順序", () => {
    const draft: AnswerDraft = { 3: { answer_text: "意見" }, 2: { so_id: 22 }, 1: { so_id: 11 } }
    expect(toAnswerPayload(QUESTIONS, draft).map((a) => a.sq_id)).toEqual([1, 2, 3])
  })
})

describe("draftFromAnswers", () => {
  it("已送出之填答轉回草稿", () => {
    const draft = draftFromAnswers([
      { sq_id: 1, so_id: 11, answer_text: null },
      { sq_id: 3, so_id: null, answer_text: "希望增加實作演練" },
    ])
    expect(draft[1]).toEqual({ so_id: 11, answer_text: undefined })
    expect(draft[3]).toEqual({ so_id: undefined, answer_text: "希望增加實作演練" })
  })

  it("當時留空的問答題不會有鍵", () => {
    // 後端 `my_answers` 不含那一題，前端據此把它呈現為「未填」。
    const draft = draftFromAnswers([{ sq_id: 1, so_id: 11, answer_text: null }])
    expect(draft[3]).toBeUndefined()
  })
})

describe("isReadOnly", () => {
  it("只有可填狀態能改", () => {
    expect(isReadOnly("FILLABLE")).toBe(false)
  })

  it.each(["SUBMITTED", "COURSE_CLOSED", "HIDDEN"] as const)("%s 為唯讀", (state) => {
    expect(isReadOnly(state)).toBe(true)
  })
})
