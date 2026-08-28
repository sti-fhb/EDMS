import { describe, expect, it } from "vitest"

import {
  EMPTY_SURVEY_QUESTION,
  SURVEY_MIN_OPTIONS,
  SURVEY_OPTION_TEXT_MAX_LEN,
  SURVEY_STEM_MAX_LEN,
  SurveyNameSchema,
  SurveyQuestionFormSchema,
  toSurveyDraft,
} from "./surveySchemas"
import type { SurveyQuestionRow } from "./surveySchemas"

describe("SurveyQuestionFormSchema", () => {
  const valid = { stem: "您對本課程是否滿意？", options: [{ option_text: "滿意" }, { option_text: "不滿意" }] }

  it("兩個選項通過", () => {
    expect(SurveyQuestionFormSchema.safeParse(valid).success).toBe(true)
  })

  it("題幹空白被擋", () => {
    const result = SurveyQuestionFormSchema.safeParse({ ...valid, stem: "   " })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe("請輸入題幹")
  })

  it.each([0, 1])("選項只有 %i 個被擋", (count) => {
    const result = SurveyQuestionFormSchema.safeParse({
      ...valid,
      options: Array.from({ length: count }, (_, i) => ({ option_text: `選項${i}` })),
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe(`每題至少需 ${SURVEY_MIN_OPTIONS} 個選項`)
  })

  it("選項無上限——與測驗題目的 2-6 不同，不可照抄 itemSchemas", () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ option_text: `選項${i}` }))
    expect(SurveyQuestionFormSchema.safeParse({ ...valid, options: many }).success).toBe(true)
  })

  it("選項文字空白被擋", () => {
    const result = SurveyQuestionFormSchema.safeParse({
      ...valid,
      options: [{ option_text: "滿意" }, { option_text: "  " }],
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe("選項文字不得為空白")
  })

  it("題幹超長被擋", () => {
    const result = SurveyQuestionFormSchema.safeParse({ ...valid, stem: "字".repeat(SURVEY_STEM_MAX_LEN + 1) })
    expect(result.success).toBe(false)
  })

  it("選項超長被擋", () => {
    const result = SurveyQuestionFormSchema.safeParse({
      ...valid,
      options: [{ option_text: "滿意" }, { option_text: "字".repeat(SURVEY_OPTION_TEXT_MAX_LEN + 1) }],
    })
    expect(result.success).toBe(false)
  })

  it("題幹與選項前後空白被去除", () => {
    const result = SurveyQuestionFormSchema.safeParse({
      stem: "  題幹  ",
      options: [{ option_text: " A " }, { option_text: " B " }],
    })
    expect(result.success).toBe(true)
    expect(result.data).toEqual({ stem: "題幹", options: [{ option_text: "A" }, { option_text: "B" }] })
  })
})

describe("EMPTY_SURVEY_QUESTION", () => {
  it("預設兩個空選項、不預填範例文字", () => {
    // #203 實測回饋明確要求「不要幫使用者填預設值，空白就好」。
    // 給兩格是因為下限就是 2，少於此存不了檔。
    expect(EMPTY_SURVEY_QUESTION.stem).toBe("")
    expect(EMPTY_SURVEY_QUESTION.options).toHaveLength(SURVEY_MIN_OPTIONS)
    expect(EMPTY_SURVEY_QUESTION.options.every((o) => o.option_text === "")).toBe(true)
  })

  it("空白初值直接送出會被擋", () => {
    expect(SurveyQuestionFormSchema.safeParse(EMPTY_SURVEY_QUESTION).success).toBe(false)
  })
})

describe("toSurveyDraft", () => {
  it("只保留可編輯欄位", () => {
    const question: SurveyQuestionRow = {
      sq_id: 7,
      stem: "題幹",
      sort_order: 2,
      version: 3,
      options: [
        { so_id: 10, option_text: "A", sort_order: 1 },
        { so_id: 11, option_text: "B", sort_order: 2 },
      ],
    }
    expect(toSurveyDraft(question)).toEqual({
      stem: "題幹",
      options: [{ option_text: "A" }, { option_text: "B" }],
    })
  })
})

describe("SurveyNameSchema", () => {
  it("空白被擋", () => {
    const result = SurveyNameSchema.safeParse("   ")
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toBe("請輸入問卷名稱")
  })

  it("正常名稱通過並去除前後空白", () => {
    expect(SurveyNameSchema.safeParse("  課後滿意度問卷 ").data).toBe("課後滿意度問卷")
  })
})
