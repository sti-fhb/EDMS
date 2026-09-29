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
  ITEM_NO_TITLE: "請開啟該項目並填寫名稱，或刪除這個未命名的項目",
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
export const BLOCKER_TARGET_KIND: Record<string, "quiz" | "chapter" | "itemChapter"> = {
  QUIZ_POINTS: "quiz",
  QUIZ_NO_QUESTION: "quiz",
  CHAPTER_EMPTY: "chapter",
  // ⭐ `ITEM_NO_TITLE`（#384）刻意對到 **itemChapter** 而非一份 item_id → 項目名稱的
  // 對照表：那個項目**依定義沒有名字**，查它會永遠落空、永遠退回裸訊息。
  //
  // 實測驗證過本表的 fail-closed 承諾：先不登記此鍵跑一次，渲染結果**恰好等於**裸訊息
  // 「教材與測驗須填寫名稱」，一個括號都沒有——確實是降級，不是標到別的物件。
  ITEM_NO_TITLE: "itemChapter",
}

/**
 * 缺漏文案要用到的三份對照表。
 *
 * 🔴 **收成具名物件而非三個位置參數**：三者都是 `Record<number, string>`，位置參數
 * 寫反會**編譯通過而且靜默標錯物件**——那正是 `BLOCKER_TARGET_KIND` 這張表當初
 * （#358 security review）要防的那一類缺陷，不該在它自己的呼叫端重新開一個。
 */
export interface BlockerNames {
  /** quiz_id → 測驗名稱 */
  quiz: Record<number, string>
  /** chapter_id → 章節名稱 */
  chapter: Record<number, string>
  /** item_id → **所屬章節**名稱（`ITEM_NO_TITLE` 用；該項目自己沒有名稱）。 */
  itemChapter: Record<number, string>
}

/**
 * 單一缺漏所指對象的文字（如 `測驗「小考」`）；無對象或查不到名稱時回 `null`。
 *
 * **`target_id` 指向哪一種物件由 `code` 決定**，不可一律當 `quiz_id`。
 *
 * ⚠️ 查不到名稱回 `null` 而非空字串——呼叫端要據此**整個略過**這個對象，而不是印出
 * 一組空的引號。這是 `BLOCKER_TARGET_KIND` fail-closed 承諾的延伸（見該表）。
 */
function blockerTargetText(blocker: PublishBlocker, names: BlockerNames): string | null {
  if (blocker.target_id === null) return null
  const kind = BLOCKER_TARGET_KIND[blocker.code]
  if (kind === "chapter") {
    const name = names.chapter[blocker.target_id]
    return name ? `章節「${name}」` : null
  }
  if (kind === "quiz") {
    const name = names.quiz[blocker.target_id]
    return name ? `測驗「${name}」` : null
  }
  if (kind === "itemChapter") {
    // 標的是項目，但顯示的是**它所屬的章節**——項目自己沒有名稱可標（#384）。
    const name = names.itemChapter[blocker.target_id]
    return name ? `章節「${name}」的項目` : null
  }
  return null
}

/**
 * 把缺漏依 `code` 分組（#412）。
 *
 * 同一種缺漏可能對應多個對象（一門課有兩個測驗配分未達 100 就是兩條），逐條列會讓
 * 教師得自己認出「這兩條其實是同一件事」，缺漏種類一多還得捲動。
 *
 * 🔴 **用 `Map` 而非物件累加**：`Map` 保有插入順序，而插入順序即後端 `evaluate_publish`
 * 的回傳順序「課程層 → 章節層 → 測驗層 → 文件層」。改用物件字面量會讓純數字字串的
 * key 被 JS 重排，⛔ 不要為了「看起來簡單」換掉它。
 */
export function groupBlockers(blockers: PublishBlocker[]): PublishBlocker[][] {
  const groups = new Map<string, PublishBlocker[]>()
  for (const blocker of blockers) {
    const existing = groups.get(blocker.code)
    if (existing) existing.push(blocker)
    else groups.set(blocker.code, [blocker])
  }
  return [...groups.values()]
}

/**
 * 一組同 `code` 缺漏的文案：訊息 + 全部對象並列。
 *
 * `PublishDialog`（發布）與課程編輯頁的再開課模式呈現的是**同一組缺漏**
 * （後端兩條路徑共用 `evaluate_publish`），故文案也共用這一支。原本兩處各自複製了
 * 一段「查 `quizNames`」的行內判斷，`CHAPTER_EMPTY` 一加就同時在兩個地方標錯。
 *
 * ⚠️ **一個對象都查不到名稱時退回裸訊息**，不印出空括號——與單一對象時的降級一致。
 */
export function blockerGroupLabel(group: PublishBlocker[], names: BlockerNames): string {
  const targets = group.map((b) => blockerTargetText(b, names)).filter((text): text is string => text !== null)
  return targets.length > 0 ? `${group[0].message}（${targets.join("、")}）` : group[0].message
}

// ── 模板（對齊後端 `app/et/survey/templates.py`）─────────────────────────────

export interface SurveyTemplateRow {
  code: string
  name: string
  description: string
  /** 題數——清單刻意不帶題目內容，教師選定後才由套用端點建立。 */
  question_count: number
}
