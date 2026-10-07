import dayjs from "dayjs"
import { describe, expect, it } from "vitest"

import { PUBLISH_FORM_OWNED, REOPEN_FORM_OWNED, blockerHighlights, checkCourseForm, mergeBlockers } from "./publishCheck"
import type { CourseFormInput } from "./publishCheck"
import type { ChapterItem } from "./schemas"

const NOW = dayjs("2027-01-01T00:00:00Z")

function input(overrides: Partial<CourseFormInput> = {}, formOverrides: Partial<CourseFormInput["form"]> = {}): CourseFormInput {
  return {
    form: {
      course_name: "採血作業訓練",
      description: "",
      require_approval: false,
      audiences: [{ unit_tag_id: 101, tag_id: 2 }],
      ...formOverrides,
    },
    startAt: NOW.add(1, "day"),
    endAt: NOW.add(10, "day"),
    startChanged: false,
    startFloor: NOW,
    startedInPast: false,
    ...overrides,
  }
}

const codes = (blockers: { code: string }[]) => blockers.map((b) => b.code)

describe("checkCourseForm", () => {
  it("全部填好時沒有任何缺漏（發布與草稿皆同）", () => {
    for (const forPublish of [true, false]) {
      const result = checkCourseForm(input(), { forPublish })
      expect(result.blockers).toEqual([])
      expect(result.fieldErrors).toEqual({})
    }
  })

  it("發布時起訖時間、受訓對象為必填；草稿不擋（使用者裁示 3）", () => {
    const empty = input({ startAt: null, endAt: null }, { audiences: [{ unit_tag_id: null, tag_id: null }] })

    const publish = checkCourseForm(empty, { forPublish: true })
    expect(codes(publish.blockers)).toEqual(["NO_SCHEDULE", "NO_TAG"])
    expect(publish.fieldErrors).toMatchObject({
      open_start_at: "請填寫課程起始時間",
      open_end_at: "請填寫課程訖止時間",
      audiences: "請設定至少 1 組受訓對象",
    })

    const draft = checkCourseForm(empty, { forPublish: false })
    expect(draft.blockers).toEqual([])
    expect(draft.fieldErrors).toEqual({})
  })

  it("起訖只缺一欄也只列一條「須填寫完整」，但只標缺的那一欄", () => {
    const result = checkCourseForm(input({ endAt: null }), { forPublish: true })
    expect(codes(result.blockers)).toEqual(["NO_SCHEDULE"])
    expect(result.fieldErrors.open_end_at).toBe("請填寫課程訖止時間")
    expect(result.fieldErrors.open_start_at).toBeUndefined()
  })

  it("課程名稱與時間錯誤一次全部回報，不因名稱錯就略過時間（草稿亦同）", () => {
    // #558 之前 `validateBasicFields` 名稱錯就提早 return，時間錯要下一次送出才看得到
    const result = checkCourseForm(input({ endAt: NOW }, { course_name: "  " }), { forPublish: false })
    expect(codes(result.blockers)).toEqual(["FORM_COURSE_NAME", "FORM_END"])
    expect(result.fieldErrors.course_name).toBe("請輸入課程名稱")
    expect(result.fieldErrors.open_end_at).toBe("課程訖止時間須晚於起始時間")
  })

  it("受訓對象一組都沒有時只列「至少 1 組」，不再重複列「有未完成的列」", () => {
    const result = checkCourseForm(input({}, { audiences: [{ unit_tag_id: 101, tag_id: null }] }), { forPublish: true })
    expect(codes(result.blockers)).toEqual(["NO_TAG"])
    // 但那一列照樣標出來——教師要知道是哪一列
    expect(result.audienceRowErrors[0]).toBeDefined()
  })

  it("已有完整配對、另有未選完的列 → 列「有未完成的列」而非「至少 1 組」", () => {
    const result = checkCourseForm(
      input({}, { audiences: [{ unit_tag_id: 101, tag_id: 2 }, { unit_tag_id: 101, tag_id: null }] }),
      { forPublish: true },
    )
    expect(codes(result.blockers)).toEqual(["FORM_AUDIENCE"])
    expect(result.audienceRowErrors[1]).toBeDefined()
    expect(result.audienceRowErrors[0]).toBeUndefined()
  })
})

describe("mergeBlockers", () => {
  const backend = [
    { code: "NO_SCHEDULE", message: "課程起訖時間須填寫完整", target_id: null },
    { code: "CHAPTER_EMPTY", message: "章節至少須有 1 份教材或測驗", target_id: 12 },
    { code: "NO_TAG", message: "課程至少須設定 1 組受訓對象", target_id: null },
  ]

  it("前端有錯時，後端的起訖／受訓對象兩項以前端為準（畫面上已填就不列）", () => {
    const merged = mergeBlockers(
      [{ code: "FORM_COURSE_NAME", message: "請輸入課程名稱", target_id: null }],
      backend,
      PUBLISH_FORM_OWNED,
    )
    expect(codes(merged)).toEqual(["FORM_COURSE_NAME", "CHAPTER_EMPTY"])
  })

  it("再開課只判過時間：後端的「沒有受訓對象」照列，不被濾掉（code review MEDIUM）", () => {
    const merged = mergeBlockers(
      [{ code: "FORM_START", message: "請重新設定課程起始時間", target_id: null }],
      backend,
      REOPEN_FORM_OWNED,
    )
    expect(codes(merged)).toEqual(["FORM_START", "CHAPTER_EMPTY", "NO_TAG"])
  })

  it("前端沒錯時後端清單原樣採用——不濾掉任何一條", () => {
    expect(mergeBlockers([], backend, PUBLISH_FORM_OWNED)).toEqual(backend)
  })
})

describe("blockerHighlights", () => {
  const chapters: ChapterItem[] = [
    {
      chapter_id: 12,
      chapter_name: "第一章",
      sort_order: 1,
      version: 0,
      items: [
        { item_id: 7, item_type: "QUIZ", title: "小考", quiz_id: 31, material_id: null, sort_order: 1, version: 0, question_count: 0 },
        { item_id: 8, item_type: "MATERIAL", title: "", quiz_id: null, material_id: 4, sort_order: 2, version: 0, question_count: null },
      ],
    },
  ] as unknown as ChapterItem[]

  it("依代碼把 target_id 對到正確的元素：章節、項目、測驗（quiz_id → 所在項目列）、問卷", () => {
    const result = blockerHighlights(
      [
        { code: "CHAPTER_EMPTY", message: "章節空", target_id: 12 },
        { code: "ITEM_NO_TITLE", message: "未命名", target_id: 8 },
        { code: "QUIZ_POINTS", message: "配分", target_id: 31 },
        { code: "SURVEY_NO_QUESTION", message: "問卷", target_id: null },
      ],
      chapters,
    )
    expect(result.chapters).toEqual({ 12: "章節空" })
    expect(result.items).toEqual({ 8: "未命名", 7: "配分" })
    expect(result.survey).toBe("問卷")
  })

  it("同一列有兩條缺漏時兩條都留著，不讓後者蓋掉前者", () => {
    const result = blockerHighlights(
      [
        { code: "ITEM_NO_TITLE", message: "未命名", target_id: 7 },
        { code: "QUIZ_NO_QUESTION", message: "無題", target_id: 31 },
      ],
      chapters,
    )
    expect(result.items[7]).toBe("未命名；無題")
  })

  it("無對應元素的缺漏不框任何東西（使用者裁示 2）", () => {
    const result = blockerHighlights(
      [
        { code: "NO_CHAPTER", message: "x", target_id: null },
        { code: "NO_MATERIAL", message: "x", target_id: null },
        { code: "OBSOLETE_DOC", message: "x", target_id: null },
      ],
      chapters,
    )
    expect(result).toEqual({ chapters: {}, items: {}, survey: null })
  })

  it("測驗缺漏的 target_id 是 quiz_id，不可當成 item_id 直接框", () => {
    // quiz_id 8 恰好等於另一個項目的 item_id——當成 item_id 會框到那個不相干的教材
    const result = blockerHighlights([{ code: "QUIZ_NO_QUESTION", message: "無題", target_id: 8 }], chapters)
    expect(result.items).toEqual({})
  })
})
