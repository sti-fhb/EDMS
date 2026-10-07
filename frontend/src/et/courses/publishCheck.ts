/**
 * 發布／再開課缺漏的前端部分（#558）：表單檢核、與後端缺漏合併、對應到畫面上要框的元素。
 *
 * ## 流程
 *
 * 按下發布 → **視窗列出全部缺漏** → 關閉視窗後缺漏處標紅框 → 補好即消失。
 *
 * 缺漏有兩個來源：
 *
 * | 來源 | 內容 | 何時知道 |
 * |---|---|---|
 * | 前端（本檔 `checkCourseForm`）| 課程名稱、描述、起訖時間、受訓對象 | 隨時（畫面上的值）|
 * | 後端 `publish-check` | 章節、教材、測驗、問卷、文件 | 已存檔的課程 |
 *
 * 前端有錯時表單**存不進去**，但章節以下的內容都是各自即時存檔的，與表單無關——故仍可用
 * 已存檔的版本問後端，兩邊合併成一份清單（使用者裁示 1）。
 *
 * ⚠️ 本檔**不改任何 state**：同一支函式既用於「按下發布那一刻」，也用於標示模式下每次
 * render 的即時重算（「補好即消失」靠的就是重算）。
 */

import type { Dayjs } from "dayjs"

import { CourseFormSchema, validateAudiences } from "./schemas"
import type { AudienceDraft, ChapterItem } from "./schemas"
import type { PublishBlocker } from "./surveySchemas"

/**
 * 前端缺漏代碼。與後端代碼**同一個命名空間**（缺漏清單依 `code` 分組、查提示）。
 *
 * ⚠️ 每個代碼只對應**一種訊息**：`groupBlockers` 依 `code` 合併、只取第一條的 `message`，
 * 兩種訊息共用一個代碼會讓第二種從清單上消失。故起、訖時間分開。
 */
export const FORM_BLOCKER = {
  courseName: "FORM_COURSE_NAME",
  description: "FORM_DESCRIPTION",
  start: "FORM_START",
  end: "FORM_END",
  audience: "FORM_AUDIENCE",
} as const

/** 與後端同義的兩項——前端以**同一個代碼、同一句訊息**產生，合併時才能以前端為準去重。 */
const NO_TAG = { code: "NO_TAG", message: "課程至少須設定 1 組受訓對象" }
const NO_SCHEDULE = { code: "NO_SCHEDULE", message: "課程起訖時間須填寫完整" }

/**
 * 後端缺漏中「由表單欄位決定」者——**呼叫端前端檢核過哪幾項，就傳哪幾項**給 `mergeBlockers`。
 *
 * 前端有錯、表單沒存時，後端讀的是**舊的**已存檔值：畫面上已填好的起訖時間，後端仍會報
 * 「須填寫完整」——清單就會與畫面矛盾。前端判過的項目以前端為準（AC 2）。
 *
 * 🔴 兩條流程判過的項目**不一樣**，不可共用一份：發布的 `checkCourseForm` 兩項都判；
 * 再開課的 `validateReopenSchedule` **只判時間**。共用的話，再開課會把後端回報的「沒有
 * 受訓對象」一併濾掉——那是前端從沒看過的真缺漏（code review MEDIUM）。
 */
export const PUBLISH_FORM_OWNED = new Set([NO_TAG.code, NO_SCHEDULE.code])
export const REOPEN_FORM_OWNED = new Set([NO_SCHEDULE.code])

export interface CourseFormInput {
  form: { course_name: string; description: string; require_approval: boolean; audiences: AudienceDraft[] }
  startAt: Dayjs | null
  endAt: Dayjs | null
  /** 起始時間是否被改動——只有改動過的值要驗「不得早於下限」（SA 裁示 2026-08-24）。 */
  startChanged: boolean
  startFloor: Dayjs
  /** 原起始時間已過（已開課）——決定「早於下限」的訊息措辭。 */
  startedInPast: boolean
}

export interface CourseFormCheck {
  /** 欄位 → 訊息（`course_name` / `description` / `open_start_at` / `open_end_at` / `audiences`）。 */
  fieldErrors: Record<string, string>
  /** 受訓對象逐列錯誤（以列索引為鍵）。 */
  audienceRowErrors: Record<number, string>
  /** 要列進缺漏視窗的項目；空陣列＝表單沒有問題。 */
  blockers: PublishBlocker[]
}

/**
 * 基本資料檢核。`forPublish` 時另檢「發布才必填」的兩項：起訖時間、至少 1 組受訓對象。
 *
 * 儲存草稿用 `forPublish: false`——草稿不擋發布必填項目（使用者裁示 3），只擋課程名稱與
 * 格式錯誤。
 */
export function checkCourseForm(input: CourseFormInput, { forPublish }: { forPublish: boolean }): CourseFormCheck {
  const { form, startAt, endAt, startChanged, startFloor, startedInPast } = input
  const fieldErrors: Record<string, string> = {}
  const blockers: PublishBlocker[] = []
  const add = (code: string, message: string) => blockers.push({ code, message, target_id: null })

  const parsed = CourseFormSchema.safeParse(form)
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const key = String(issue.path[0])
      if (!fieldErrors[key]) fieldErrors[key] = issue.message
    }
  }
  if (fieldErrors.course_name) add(FORM_BLOCKER.courseName, fieldErrors.course_name)
  if (fieldErrors.description) add(FORM_BLOCKER.description, fieldErrors.description)

  // 時間規則：起始須 ≥ 下限（只對改動過的值）、訖止須晚於起始（後端亦強制，此處為即時回饋）
  if (startChanged && startAt && startAt.isBefore(startFloor)) {
    fieldErrors.open_start_at = startedInPast ? "課程已開課，起始時間不可再往前調整" : "課程起始時間不可早於目前時間"
    add(FORM_BLOCKER.start, fieldErrors.open_start_at)
  }
  if (startAt && endAt && !endAt.isAfter(startAt)) {
    fieldErrors.open_end_at = "課程訖止時間須晚於起始時間"
    add(FORM_BLOCKER.end, fieldErrors.open_end_at)
  }
  if (forPublish && (!startAt || !endAt)) {
    if (!startAt) fieldErrors.open_start_at = "請填寫課程起始時間"
    if (!endAt) fieldErrors.open_end_at = "請填寫課程訖止時間"
    add(NO_SCHEDULE.code, NO_SCHEDULE.message)
  }

  const { rowErrors, payload } = validateAudiences(form.audiences, { forPublish })
  if (forPublish && payload.length === 0) {
    // 一組都沒有：列「至少 1 組」即可，不再另列「有未完成的列」——預帶的那列空白就是
    // 未完成的列，兩條講的是同一件事
    fieldErrors.audiences = "請設定至少 1 組受訓對象"
    add(NO_TAG.code, NO_TAG.message)
  } else if (Object.keys(rowErrors).length > 0) {
    add(FORM_BLOCKER.audience, "受訓對象有未選完或重複的列")
  }

  return { fieldErrors, audienceRowErrors: rowErrors, blockers }
}

/**
 * 前端缺漏 + 後端缺漏 → 一份清單（前端在前）。
 *
 * 前端沒有缺漏時，表單已存檔、後端讀到的就是畫面上的值，**後端清單原樣採用**——不濾掉
 * 任何一條，避免把真正的缺漏藏起來。
 *
 * @param formOwned 前端**實際檢核過**的後端代碼（`PUBLISH_FORM_OWNED` / `REOPEN_FORM_OWNED`）
 */
export function mergeBlockers(
  formBlockers: PublishBlocker[],
  backend: PublishBlocker[],
  formOwned: ReadonlySet<string>,
): PublishBlocker[] {
  if (formBlockers.length === 0) return backend
  return [...formBlockers, ...backend.filter((b) => !formOwned.has(b.code))]
}

export interface BlockerHighlights {
  /** chapter_id → 訊息 */
  chapters: Record<number, string>
  /** item_id → 訊息（測驗缺漏的 `target_id` 是 quiz_id，已換成所在的項目列） */
  items: Record<number, string>
  /** 課後問卷之缺漏訊息；無則 null */
  survey: string | null
}

/**
 * 後端缺漏 → 畫面上要框的元素。
 *
 * 無對應元素者（`NO_CHAPTER` / `NO_MATERIAL` / `OBSOLETE_DOC`）**不出現在結果裡**，只列在
 * 視窗中（使用者裁示 2：不能標示的就算了）。
 *
 * 🔴 `target_id` 的意義依 `code` 而定（見 `BLOCKER_TARGET_KIND`）：`CHAPTER_EMPTY` 是
 * chapter_id、`ITEM_NO_TITLE` 是 item_id、測驗兩項是 **quiz_id**。三者是各自獨立的序號，
 * 一律當成同一種 id 會框到不相干的列。未登記的代碼一律不框（fail-closed）。
 */
export function blockerHighlights(blockers: PublishBlocker[], chapters: ChapterItem[]): BlockerHighlights {
  const itemByQuiz: Record<number, number> = {}
  for (const chapter of chapters) {
    for (const item of chapter.items ?? []) {
      if (item.quiz_id !== null && item.quiz_id !== undefined) itemByQuiz[item.quiz_id] = item.item_id
    }
  }
  const result: BlockerHighlights = { chapters: {}, items: {}, survey: null }
  // 同一列可能同時有兩條（例如未命名的測驗又沒有題目）——併成一句，不讓後者蓋掉前者
  const append = (map: Record<number, string>, id: number, message: string) => {
    map[id] = map[id] ? `${map[id]}；${message}` : message
  }
  for (const b of blockers) {
    if (b.code === "SURVEY_NO_QUESTION") {
      result.survey = b.message
      continue
    }
    if (b.target_id === null) continue
    if (b.code === "CHAPTER_EMPTY") append(result.chapters, b.target_id, b.message)
    else if (b.code === "ITEM_NO_TITLE") append(result.items, b.target_id, b.message)
    else if (b.code === "QUIZ_NO_QUESTION" || b.code === "QUIZ_POINTS") {
      const itemId = itemByQuiz[b.target_id]
      if (itemId !== undefined) append(result.items, itemId, b.message)
    }
  }
  return result
}
