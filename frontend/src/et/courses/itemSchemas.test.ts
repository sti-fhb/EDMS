import { describe, expect, it } from "vitest"

import { QuestionFormSchema, QuizFormSchema, formatDuration, formatFileSize, isBlankHtml } from "./itemSchemas"

describe("formatDuration", () => {
  it.each([
    [0, "0:00"],
    [5, "0:05"],
    [65, "1:05"],
    [180, "3:00"],
    [599, "9:59"],
    [3600, "1:00:00"],
    [3725, "1:02:05"],
  ])("%i 秒 → %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })
})

describe("formatFileSize", () => {
  it.each([
    [512, "512 B"],
    [1024, "1.0 KB"],
    [1536, "1.5 KB"],
    [1024 * 1024, "1.0 MB"],
    [1024 * 1024 * 180, "180 MB"],
    [1024 * 1024 * 1024 * 2, "2.0 GB"],
  ])("%i bytes → %s", (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected)
  })
})

describe("isBlankHtml", () => {
  it("空字串視為空白", () => {
    expect(isBlankHtml("")).toBe(true)
  })

  it("編輯器清空後留下的空段落視為空白", () => {
    // TipTap 清空內容後留下 <p></p> 而非空字串。原樣送給後端會讓它認定「有說明文字」，
    // 使一個三類媒材皆空的教材通過檢核——那正是 ET_MATERIAL_002 要擋的狀態。
    expect(isBlankHtml("<p></p>")).toBe(true)
  })

  it("只有空白字元與 nbsp 視為空白", () => {
    expect(isBlankHtml("<p>&nbsp; </p>")).toBe(true)
  })

  it("有實質文字則不視為空白", () => {
    expect(isBlankHtml("<p>說明</p>")).toBe(false)
  })

  it("巢狀標籤中的文字仍算有內容", () => {
    expect(isBlankHtml("<ul><li><strong>重點</strong></li></ul>")).toBe(false)
  })
})

describe("QuizFormSchema", () => {
  const base = { quiz_name: "測驗", description: "", pass_score: 80, time_limit_min: null, max_retry: 3 }

  it("合法設定通過", () => {
    expect(QuizFormSchema.safeParse(base).success).toBe(true)
  })

  it("時間限制留空（null）＝不限時，合法", () => {
    expect(QuizFormSchema.safeParse({ ...base, time_limit_min: null }).success).toBe(true)
  })

  it("時間限制為 0 不合法", () => {
    // 兩態語意：null = 不限時、>= 1 = 限時。0 不在其中——放行會讓「限時 0 分鐘」
    // 這種無從作答的設定進到 DB。
    expect(QuizFormSchema.safeParse({ ...base, time_limit_min: 0 }).success).toBe(false)
  })

  it.each([-1, 101])("及格分數 %i 不合法", (pass_score) => {
    expect(QuizFormSchema.safeParse({ ...base, pass_score }).success).toBe(false)
  })

  it.each([-1, 1000])("重考次數 %i 不合法", (max_retry) => {
    expect(QuizFormSchema.safeParse({ ...base, max_retry }).success).toBe(false)
  })

  it("重考次數 0 合法（＝不允許重考）", () => {
    expect(QuizFormSchema.safeParse({ ...base, max_retry: 0 }).success).toBe(true)
  })
})

describe("QuestionFormSchema", () => {
  const option = (option_text: string, is_correct = false) => ({ option_text, is_correct })
  const base = {
    question_type: "SINGLE" as const,
    stem: "題幹",
    points: 20,
    options: [option("A", true), option("B")],
  }

  it("單選題恰好一個正確選項通過", () => {
    expect(QuestionFormSchema.safeParse(base).success).toBe(true)
  })

  it.each([0, 1])("選項只有 %i 個被擋", (count) => {
    // UI 已於達下限時停用刪除鈕（見 QuestionEditor），所以正常操作到不了這裡——
    // 這條守的是**繞過 UI 直接送出**的請求，故必須在 schema 層留著測試。
    const result = QuestionFormSchema.safeParse({
      ...base,
      options: Array.from({ length: count }, (_, i) => option(`X${i}`, i === 0)),
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toContain("每題選項數須介於 2 至 6 個")
  })

  it("選項超過 6 個被擋", () => {
    const result = QuestionFormSchema.safeParse({
      ...base,
      options: Array.from({ length: 7 }, (_, i) => option(`X${i}`, i === 0)),
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0]?.message).toContain("每題選項數須介於 2 至 6 個")
  })

  it("單選題兩個正確選項被擋", () => {
    const result = QuestionFormSchema.safeParse({ ...base, options: [option("A", true), option("B", true)] })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0].message).toContain("單選題")
  })

  it("單選題零個正確選項被擋", () => {
    const result = QuestionFormSchema.safeParse({ ...base, options: [option("A"), option("B")] })
    expect(result.success).toBe(false)
  })

  it("多選題可有多個正確選項", () => {
    const result = QuestionFormSchema.safeParse({
      ...base,
      question_type: "MULTIPLE",
      options: [option("A", true), option("B", true), option("C")],
    })
    expect(result.success).toBe(true)
  })

  it("多選題零個正確選項被擋且訊息指明題型", () => {
    const result = QuestionFormSchema.safeParse({
      ...base,
      question_type: "MULTIPLE",
      options: [option("A"), option("B")],
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0].message).toContain("多選題")
  })

  it("兩種題型的訊息不同——否則教師不知道要怎麼改", () => {
    const single = QuestionFormSchema.safeParse({ ...base, options: [option("A", true), option("B", true)] })
    const multiple = QuestionFormSchema.safeParse({
      ...base,
      question_type: "MULTIPLE",
      options: [option("A"), option("B")],
    })
    expect(single.error?.issues[0].message).not.toBe(multiple.error?.issues[0].message)
  })

  it("選項少於 2 個被擋", () => {
    expect(QuestionFormSchema.safeParse({ ...base, options: [option("A", true)] }).success).toBe(false)
  })

  it("選項多於 6 個被擋", () => {
    const options = Array.from({ length: 7 }, (_, i) => option(`O${i}`, i === 0))
    expect(QuestionFormSchema.safeParse({ ...base, options }).success).toBe(false)
  })

  it("題幹空白被擋", () => {
    expect(QuestionFormSchema.safeParse({ ...base, stem: "   " }).success).toBe(false)
  })

  it("選項文字空白被擋", () => {
    expect(QuestionFormSchema.safeParse({ ...base, options: [option("  ", true), option("B")] }).success).toBe(false)
  })

  it.each([-1, 101])("配分 %i 被擋", (points) => {
    expect(QuestionFormSchema.safeParse({ ...base, points }).success).toBe(false)
  })
})
