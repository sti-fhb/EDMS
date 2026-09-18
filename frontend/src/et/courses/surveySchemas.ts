/** ET02 課後問卷型別與表單驗證（對齊後端 `app/et/survey/schemas.py`）。 */

import { z } from "zod"

/** 對齊後端：`SURVEY_NAME` VARCHAR(100)、`STEM` VARCHAR(500)、`OPTION_TEXT` VARCHAR(200)。 */
export const SURVEY_NAME_MAX_LEN = 100
export const SURVEY_STEM_MAX_LEN = 500
export const SURVEY_OPTION_TEXT_MAX_LEN = 200

/**
 * 每題選項數下限（`data-model` §ET_SURVEY_OPTION）。
 *
 * **無上限**——與測驗題目的 2–6 不同，不可照抄 `itemSchemas.MAX_OPTIONS`。後端只在
 * schema 層設一個寬鬆的請求大小防護（20），那不是業務規則，前端因此不設加入按鈕的
 * 停用條件。
 */
export const SURVEY_MIN_OPTIONS = 2

/** 問卷題型（對齊後端 `ET_SURVEY_QUESTION_TYPE`）。 */
export type SurveyQuestionType = "SINGLE" | "TEXT"

export const SURVEY_QUESTION_TYPE_LABEL: Record<SurveyQuestionType, string> = {
  SINGLE: "單選",
  TEXT: "問答",
}

/** 問答題之學員答案上限（#238）；本 issue 僅作為說明文字，實際輸入端屬 `ET-15`。 */
export const SURVEY_ANSWER_MAX_LEN = 150

export interface SurveyOptionRow {
  so_id: number
  option_text: string
  sort_order: number
}

export interface SurveyQuestionRow {
  sq_id: number
  question_type: SurveyQuestionType
  stem: string
  sort_order: number
  version: number
  options: SurveyOptionRow[]
}

export interface SurveyDetail {
  survey_id: number
  course_id: number
  survey_name: string
  is_active: boolean
  version: number
  /**
   * 已有任何填答 → 題目與選項凍結（AC 21）。**停用不受此限**。
   *
   * 問卷名稱原本也不受此限，自 #364（2026-09-18 裁示）起前端一併收起改名入口；
   * ⚠️ 後端 update 仍放行改名，此處只影響 UI。
   */
  frozen: boolean
  responded_count: number
  pending_count: number
  questions: SurveyQuestionRow[]
}

/** 題目編輯中的草稿——選項尚未落地，故只有文字。 */
export interface SurveyQuestionDraft {
  question_type: SurveyQuestionType
  stem: string
  options: { option_text: string }[]
}

/**
 * 新題目的初始值。
 *
 * 預設兩個**空**選項而非填好的範例文字：#203 實測回饋明確要求「不要幫使用者填預設
 * 值，空白就好」。給兩格是因為下限就是 2，少於此存不了檔。
 */
export const EMPTY_SURVEY_QUESTION: SurveyQuestionDraft = {
  question_type: "SINGLE",
  stem: "",
  options: [{ option_text: "" }, { option_text: "" }],
}

/** 把後端回的題目轉為可編輯草稿。 */
export function toSurveyDraft(question: SurveyQuestionRow): SurveyQuestionDraft {
  return {
    question_type: question.question_type,
    stem: question.stem,
    options: question.options.map((o) => ({ option_text: o.option_text })),
  }
}

/**
 * 問卷題目表單驗證，對齊後端 `SurveyQuestionCreateReq` + `ensure_option_count_valid`。
 *
 * 前端擋一次、後端再擋一次：前端是為了讓教師當場看到哪裡不對，後端擋的是繞過 UI
 * 的請求。兩者訊息刻意一致，避免同一個問題在兩處講法不同。
 */
export const SurveyQuestionFormSchema = z
  .object({
    question_type: z.enum(["SINGLE", "TEXT"]),
    stem: z
      .string()
      .trim()
      .min(1, { message: "請輸入題幹" })
      .max(SURVEY_STEM_MAX_LEN, { message: `題幹不可超過 ${SURVEY_STEM_MAX_LEN} 字` }),
    options: z.array(
      z.object({
        option_text: z
          .string()
          .trim()
          .min(1, { message: "選項文字不得為空白" })
          .max(SURVEY_OPTION_TEXT_MAX_LEN, { message: `選項不可超過 ${SURVEY_OPTION_TEXT_MAX_LEN} 字` }),
      }),
    ),
  })
  // 選項數之要求隨題型而異，故不能寫成 `.min()`——那是無條件的。
  // 對齊後端 `rules.ensure_options_match_type`：單選至少 2、問答必須 0 個。
  .superRefine((value, ctx) => {
    if (value.question_type === "TEXT") {
      if (value.options.length > 0) {
        ctx.addIssue({ code: "custom", message: "問答題不可設定選項", path: ["options"] })
      }
      return
    }
    if (value.options.length < SURVEY_MIN_OPTIONS) {
      ctx.addIssue({
        code: "custom",
        message: `每題至少需 ${SURVEY_MIN_OPTIONS} 個選項`,
        path: ["options"],
      })
    }
  })

export type SurveyQuestionFormValues = z.infer<typeof SurveyQuestionFormSchema>

/** 問卷名稱驗證，對齊後端 `SurveyCreateReq`。 */
export const SurveyNameSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入問卷名稱" })
  .max(SURVEY_NAME_MAX_LEN, { message: `問卷名稱不可超過 ${SURVEY_NAME_MAX_LEN} 字元` })

// ── 發布檢核（對齊後端 `app/et/course/publish_rules.py`）─────────────────────

export interface PublishBlocker {
  code: string
  message: string
  /** 出問題的測驗 ID；課程層缺漏為 null。 */
  target_id: number | null
}

export interface PublishCheckResult {
  can_publish: boolean
  blockers: PublishBlocker[]
}

export interface PublishResult {
  course_id: number
  status: string
  invitation_code: string
  version: number
  /** 依受訓單位標籤自動帶入之學員數（#247）。0 通常代表標籤沒掛到任何人。 */
  invited_count: number
}

/**
 * 缺漏代碼 → 該去修哪一區塊。
 *
 * 訊息本身由後端給（靜態文案），這裡只補「去哪裡修」——後端不該知道前端的區塊名稱。
 */
export const BLOCKER_HINT: Record<string, string> = {
  NO_CHAPTER: "請於「章節」區塊新增至少 1 個章節",
  NO_MATERIAL: "請於章節內新增至少 1 份教材",
  CHAPTER_EMPTY: "請於該章節新增教材或測驗，或刪除這個空章節",
  NO_TAG: "請於「基本資料」選擇受訓單位標籤",
  NO_SCHEDULE: "請於「基本資料」填寫課程起訖時間",
  QUIZ_POINTS: "請調整該測驗各題配分，使總和為 100",
  QUIZ_NO_QUESTION: "請為該測驗新增至少 1 題",
  SURVEY_NO_QUESTION: "請為課後問卷新增至少 1 題，或停用該問卷",
  OBSOLETE_DOC: "請於教材中移除已廢止文件之引用",
}

/**
 * 缺漏代碼 → 其 `target_id` 指向哪一種物件。
 *
 * 🔴 **`target_id` 的意義依 `code` 而定，不是一律 `quiz_id`。** `CHAPTER_EMPTY`
 * （#358 第 3 項）帶的是 `chapter_id`，而 `chapter_id` 與 `quiz_id` 是兩個各自獨立
 * 的序號：
 *
 * - 撞號時 → 空章節會被標成「（測驗「某測驗」）」，指向一個毫不相干的物件
 * - 不撞號時 → 名稱整個查不到，教師看不出是哪一章，後端帶 `target_id` 的用途落空
 *
 * ⚠️ **未列於此表的代碼一律不標名稱**（fail-closed）。日後新增帶 `target_id` 的代碼
 * 若忘了登記，結果是「少一段括號」而不是「標到別的東西」。
 */
export const BLOCKER_TARGET_KIND: Record<string, "quiz" | "chapter"> = {
  QUIZ_POINTS: "quiz",
  QUIZ_NO_QUESTION: "quiz",
  CHAPTER_EMPTY: "chapter",
}

/**
 * 缺漏文案——**`target_id` 指向哪一種物件由 `code` 決定**，不可一律當 `quiz_id`。
 *
 * `PublishDialog`（發布）與 `ReopenCourseDialog`（再開課）呈現的是**同一組缺漏**
 * （後端兩條路徑共用 `evaluate_publish`），故文案也共用這一支。原本兩處各自複製了
 * 一段「查 `quizNames`」的行內判斷，`CHAPTER_EMPTY` 一加就同時在兩個地方標錯。
 */
export function blockerLabel(
  blocker: PublishBlocker,
  quizNames: Record<number, string>,
  chapterNames: Record<number, string>,
): string {
  if (blocker.target_id === null) return blocker.message
  const kind = BLOCKER_TARGET_KIND[blocker.code]
  if (kind === "chapter") {
    const name = chapterNames[blocker.target_id]
    return name ? `${blocker.message}（章節「${name}」）` : blocker.message
  }
  if (kind === "quiz") {
    const name = quizNames[blocker.target_id]
    return name ? `${blocker.message}（測驗「${name}」）` : blocker.message
  }
  return blocker.message
}

// ── 模板（對齊後端 `app/et/survey/templates.py`）─────────────────────────────

export interface SurveyTemplateRow {
  code: string
  name: string
  description: string
  /** 題數——清單刻意不帶題目內容，教師選定後才由套用端點建立。 */
  question_count: number
}
