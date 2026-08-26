/**
 * ET02 章節項目、教材與測驗型別（對齊後端 `app/et/course/schemas.py`、
 * `app/et/material/schemas.py`、`app/et/quiz/schemas.py`）。
 */

import { z } from "zod"

export const ITEM_TITLE_MAX_LEN = 100
export const MATERIAL_NAME_MAX_LEN = 100
export const DESCRIPTION_HTML_MAX_LEN = 50_000
export const QUIZ_NAME_MAX_LEN = 100
export const QUIZ_DESCRIPTION_MAX_LEN = 5_000
export const STEM_MAX_LEN = 500
export const OPTION_TEXT_MAX_LEN = 200
/** 每題選項數上下限（data-model §ET_OPTION；後端 `ET_QUESTION_003` 亦擋一次）。 */
export const MIN_OPTIONS = 2
export const MAX_OPTIONS = 6
/** 一份測驗之各題配分總和目標——UI 常駐顯示「90 / 100」，未達不阻擋儲存（屬 #204 發布檢核）。 */
export const POINTS_TOTAL_TARGET = 100

export type ItemType = "MATERIAL" | "QUIZ"
export type QuestionType = "SINGLE" | "MULTIPLE"

export const ITEM_TYPE_LABEL: Record<ItemType, string> = {
  MATERIAL: "教材",
  QUIZ: "測驗",
}

export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  SINGLE: "單選",
  MULTIPLE: "多選",
}

export interface ItemRow {
  item_id: number
  item_type: string
  /** 取自對應之 `MATERIAL_NAME` / `QUIZ_NAME`——項目本身不存名稱。 */
  title: string
  sort_order: number
  material_id: number | null
  quiz_id: number | null
  version: number
}

// ── 教材 ────────────────────────────────────────────────────────────────────

export interface VideoRow {
  video_id: number
  file_name: string
  duration_sec: number
  file_size_bytes: number
  sort_order: number
}

export interface DocRow {
  mat_doc_id: number
  doc_id: string
  /** DM 端即時查得；`unavailable` 時為 null。 */
  doc_name: string | null
  version_no: string | null
  /** 已廢止——顯示警告（ET-MSG-ET02-002），僅可逐筆刪除。 */
  obsolete: boolean
  /** DM 端取不到（文件被刪、無發布版）。與「已廢止」不同：廢止仍讀得到最後版。 */
  unavailable: boolean
  sort_order: number
}

export interface MaterialDetail {
  material_id: number
  material_name: string
  description_html: string | null
  version: number
  videos: VideoRow[]
  docs: DocRow[]
}

export interface DmDocOption {
  doc_id: string
  doc_name: string
  version_no: string
  published_date: string | null
}

// ── 測驗 ────────────────────────────────────────────────────────────────────

export interface OptionRow {
  option_id: number
  option_text: string
  is_correct: boolean
  sort_order: number
}

export interface QuestionRow {
  question_id: number
  question_type: string
  stem: string
  points: number
  sort_order: number
  version: number
  options: OptionRow[]
}

export interface QuizDetail {
  quiz_id: number
  quiz_name: string
  description: string | null
  pass_score: number
  time_limit_min: number | null
  max_retry: number
  version: number
  questions: QuestionRow[]
  /** 後端算出之配分總和——UI 常駐顯示，未達 100 不阻擋儲存。 */
  points_total: number
}

// ── 表單驗證（Zod）──────────────────────────────────────────────────────────

/** 新增項目：教材 / 測驗共用同一個名稱欄位。 */
export const ItemTitleSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入名稱" })
  .max(ITEM_TITLE_MAX_LEN, { message: `名稱不可超過 ${ITEM_TITLE_MAX_LEN} 字元` })

export const MaterialFormSchema = z.object({
  material_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入教材名稱" })
    .max(MATERIAL_NAME_MAX_LEN, { message: `教材名稱不可超過 ${MATERIAL_NAME_MAX_LEN} 字元` }),
  description_html: z
    .string()
    .max(DESCRIPTION_HTML_MAX_LEN, { message: "說明文字過長" }),
})

export type MaterialFormValues = z.infer<typeof MaterialFormSchema>

export const QuizFormSchema = z.object({
  quiz_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入測驗名稱" })
    .max(QUIZ_NAME_MAX_LEN, { message: `測驗名稱不可超過 ${QUIZ_NAME_MAX_LEN} 字元` }),
  /** 純文字（SA 裁示 #203 Q1）——不經 HTML 消毒，渲染時亦不得注入 HTML。 */
  description: z
    .string()
    .max(QUIZ_DESCRIPTION_MAX_LEN, { message: `測驗說明不可超過 ${QUIZ_DESCRIPTION_MAX_LEN} 字` }),
  pass_score: z
    .number({ message: "請輸入及格分數" })
    .int({ message: "及格分數須為整數" })
    .min(0, { message: "及格分數須介於 0 至 100" })
    .max(100, { message: "及格分數須介於 0 至 100" }),
  /** `null` = 不限時；`>= 1` = 限時 N 分鐘（後端之兩態語意，0 不是有效值）。 */
  time_limit_min: z
    .number()
    .int({ message: "時間限制須為整數" })
    .min(1, { message: "時間限制須至少 1 分鐘；留空表示不限時" })
    .nullable(),
  max_retry: z
    .number({ message: "請輸入重考次數上限" })
    .int({ message: "重考次數須為整數" })
    .min(0, { message: "重考次數須介於 0 至 999" })
    .max(999, { message: "重考次數須介於 0 至 999" }),
})

export type QuizFormValues = z.infer<typeof QuizFormSchema>

/**
 * 題目驗證——與後端 `rules.py` 同一組規則，訊息刻意一致。
 *
 * 前端擋是為了即時回饋，**不是**後端可以少擋：繞過 UI 直接打 API 時只有後端擋得住。
 */
export const QuestionFormSchema = z
  .object({
    question_type: z.enum(["SINGLE", "MULTIPLE"]),
    stem: z
      .string()
      .trim()
      .min(1, { message: "請輸入題幹" })
      .max(STEM_MAX_LEN, { message: `題幹不可超過 ${STEM_MAX_LEN} 字` }),
    // 下限 1：0 分的題目答對答錯都不影響成績，等同不存在卻仍佔作答時間
    points: z
      .number({ message: "請輸入配分" })
      .int({ message: "配分須為整數" })
      .min(1, { message: "配分須介於 1 至 100" })
      .max(100, { message: "配分須介於 1 至 100" }),
    options: z
      .array(
        z.object({
          option_text: z
            .string()
            .trim()
            .min(1, { message: "選項文字不得為空" })
            .max(OPTION_TEXT_MAX_LEN, { message: `選項文字不可超過 ${OPTION_TEXT_MAX_LEN} 字` }),
          is_correct: z.boolean(),
        }),
      )
      .min(MIN_OPTIONS, { message: `每題選項數須介於 ${MIN_OPTIONS} 至 ${MAX_OPTIONS} 個` })
      .max(MAX_OPTIONS, { message: `每題選項數須介於 ${MIN_OPTIONS} 至 ${MAX_OPTIONS} 個` }),
  })
  .superRefine((value, ctx) => {
    // 用 superRefine 而非 refine：兩種題型的違規原因不同，訊息必須跟著題型變，
    // 而 refine 的第二參數只吃靜態值。訊息與後端 `rules.ensure_correct_options_valid`
    // 刻意一致——同一條規則在兩端說法不同會讓人以為是兩件事。
    const correct = value.options.filter((o) => o.is_correct).length
    const ok = value.question_type === "SINGLE" ? correct === 1 : correct >= 1
    if (!ok) {
      ctx.addIssue({
        code: "custom",
        path: ["options"],
        message:
          value.question_type === "SINGLE" ? "單選題須恰好指定 1 個正確選項" : "多選題須至少指定 1 個正確選項",
      })
    }
  })

export type QuestionFormValues = z.infer<typeof QuestionFormSchema>

/** 題目編輯中的暫存值（尚未落地，故無 id）。 */
export interface QuestionDraft {
  question_type: QuestionType
  stem: string
  points: number
  options: { option_text: string; is_correct: boolean }[]
}

/** 新增題目時的初始值——單選、兩個空選項、第一個預設為正確。 */
export const EMPTY_QUESTION: QuestionDraft = {
  question_type: "SINGLE",
  stem: "",
  // 預設 1 而非 0——0 分不合法，讓使用者一開啟就踩到驗證錯誤沒有意義
  points: 1,
  options: [
    { option_text: "", is_correct: true },
    { option_text: "", is_correct: false },
  ],
}

/**
 * 判斷一段 HTML 是否無實質內容。
 *
 * TipTap 在使用者清空內容後留下的是 `<p></p>` 而非空字串。若原樣送給後端，
 * 後端會認定「說明文字有值」而讓一個三類媒材皆空的教材通過檢核——那正是
 * `ET_MATERIAL_002` 要擋的狀態。
 */
export function isBlankHtml(html: string): boolean {
  return html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim().length === 0
}

// ── 顯示格式 ────────────────────────────────────────────────────────────────

/** 秒數轉 `mm:ss` / `h:mm:ss`（影片長度顯示）。 */
export function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const mm = String(minutes).padStart(hours > 0 ? 2 : 1, "0")
  const ss = String(seconds).padStart(2, "0")
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

/** 位元組轉人類可讀（影片檔案大小顯示）。 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB"]
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  // 小於 10 時保留一位小數（1.5 MB 比 2 MB 有資訊量），其餘取整
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unitIndex]}`
}
