/** ET05 課程骨架與章節編排型別（對齊後端 app/et/course/schemas.py）。 */

import type { ItemRow } from "./itemSchemas"

/** 課程描述長度上限——與後端 `DESCRIPTION_MAX_LEN` 同步（spec_us3 AC 1「至多 500 字」）。 */
export const DESCRIPTION_MAX_LEN = 500
export const COURSE_NAME_MAX_LEN = 100
export const CHAPTER_NAME_MAX_LEN = 100

export interface ChapterItem {
  chapter_id: number
  chapter_name: string
  sort_order: number
  version: number
  /** 章節下之教材 / 測驗項目（#203）。新增模式之暫存章節恆為空陣列。 */
  items: ItemRow[]
}

export interface CourseDetail {
  course_id: number
  course_name: string
  description: string | null
  status: string
  open_start_at: string | null
  open_end_at: string | null
  require_approval: boolean
  version: number
  owner_id: string
  /** 建立者姓名（唯讀 join DP_USER；**查無此人**時 null）——檢視模式 banner 用。 */
  owner_name: string | null
  /**
   * 建立者帳號是否已停用（#330）。用 `ownerLabel()` 組字串，不要各頁自己拼。
   *
   * 來源是後端的 `DP_USER.STATUS`——**不是** `DELETED`（EDMS 沒有刪除使用者的功能，
   * 那個欄位恆為 0）。
   */
  owner_is_disabled: boolean
  /** 當前使用者是否為擁有者；false 時全頁唯讀（spec.md §擁有權判定）。 */
  is_owner: boolean
  /** 受訓對象 `(單位, 職位)` 配對（#538）。 */
  audiences: AudiencePair[]
  chapters: ChapterItem[]
  /** 課程邀請碼；**僅 owner 可見**，非擁有者後端回 null（#247）。 */
  invitation_code: string | null
}

export interface TagOption {
  tag_id: number
  tag_name: string
  /** false 只會出現在「課程既有已掛之停用標籤」——不得再新掛（FR-ET-US3-03）。 */
  is_active: boolean
  /** `UNIT`（單位）/ `AUDIENCE`（職位）——配對的兩個下拉各取一類（#538）。 */
  tag_type: "UNIT" | "AUDIENCE"
  /** 通用值（「全單位」/「全體」）。 */
  is_all: boolean
}

/** 一組受訓對象配對（後端回應）。`label` 由後端組好，各頁直接顯示，不要自己拼（#538）。 */
export interface AudiencePair {
  unit_tag_id: number
  tag_id: number
  label: string
}

/** 送往後端的一組配對——兩欄皆必填。 */
export interface AudiencePairPayload {
  unit_tag_id: number
  tag_id: number
}

/**
 * 編輯中的一列配對。兩欄可暫時為 `null`（新增的空白列、只選了一欄）；送出前由
 * `validateAudiences` 擋下不完整的列。
 */
export interface AudienceDraft {
  unit_tag_id: number | null
  tag_id: number | null
}

/** 配對的比對鍵——判斷重複、判斷是否為已發布課程的既有列。 */
export const audienceKey = (p: { unit_tag_id: number | null; tag_id: number | null }) =>
  `${p.unit_tag_id ?? ""}:${p.tag_id ?? ""}`

/**
 * 送出前的配對檢核。
 *
 * - 兩欄都空的列：存草稿時**忽略**；**發布時視為錯誤**——發布即依配對帶入學員，教師
 *   應明確決定那一列要填還是刪，而非由系統靜默略過（使用者手測回饋）。存草稿不擋：新增
 *   課程預帶一列空白，擋了等於逼教師先刪列才能存草稿
 * - 只選了一欄 → 該列錯誤：半組配對在後端不成立，存進去只會讓教師以為設好了
 * - 重複 → 第二次出現的那列錯誤：後端會 422
 *
 * @returns `rowErrors` 以列索引為鍵；`payload` 為可送出的完整配對（`rowErrors` 為空時才有意義）。
 */
export function validateAudiences(
  rows: AudienceDraft[],
  { forPublish = false }: { forPublish?: boolean } = {},
): {
  rowErrors: Record<number, string>
  payload: AudiencePairPayload[]
} {
  const rowErrors: Record<number, string> = {}
  const seen = new Set<string>()
  const payload: AudiencePairPayload[] = []
  rows.forEach((row, idx) => {
    if (row.unit_tag_id === null && row.tag_id === null && !forPublish) return
    if (row.unit_tag_id === null || row.tag_id === null) {
      rowErrors[idx] = "請選擇單位與職位，或刪除此列"
      return
    }
    const key = audienceKey(row)
    if (seen.has(key)) {
      rowErrors[idx] = "此組受訓對象已存在"
      return
    }
    seen.add(key)
    payload.push({ unit_tag_id: row.unit_tag_id, tag_id: row.tag_id })
  })
  return { rowErrors, payload }
}

export interface CourseCreateResult {
  course_id: number
  version: number
}

export interface Capabilities {
  /** 具教師角色（SA 裁示 Q2）→ 顯示「新增課程」入口，以及課程列表的「我建立的」分頁。 */
  can_create_course: boolean
  /**
   * 具教師或管理者角色 → 顯示側欄之**課程列表**與課程編輯頁。
   *
   * ⚠️ **不涵蓋學員頁與核可查詢**，儘管它曾經是那兩者的判定來源：學員頁改用
   * `can_track_students`（#463），核可查詢則**刻意不掛任何旗標**（兩種角色都要進得去，
   * 看到的內容不同）。
   */
  can_manage_courses: boolean
  /**
   * 具**教師**角色 → 顯示側欄之「學員」。
   *
   * 🔴 與 `can_create_course` 今天同值但**問的是不同的事**（能不能開課 vs 有沒有學員
   * 可追蹤）；與 `can_manage_courses` 的差別則是它涵蓋管理者，而管理者的學員頁是空的
   *（課程下拉為 `scope=mine`）——那正是 #463 要修的東西。完整理由見後端
   * `app/et/course/schemas.py` 的 `Capabilities`。
   */
  can_track_students: boolean
  /** 具學員角色 → 顯示側欄「我的課程」。 */
  can_learn: boolean
}

export interface CoursePayload {
  course_name: string
  description: string | null
  open_start_at: string | null
  open_end_at: string | null
  require_approval: boolean
  audiences: AudiencePairPayload[]
}

/** 建立課程可一併帶章節名稱——使新增流程不必「先存草稿才能加章節」（後端同一交易內建立）。 */
export interface CourseCreatePayload extends CoursePayload {
  chapters: string[]
}

/** 課程狀態（ET_COURSE_STATUS）。本 issue 僅寫入 DRAFT；發布屬 #204。 */
export const COURSE_STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  PUBLISHED: "已發布",
  CLOSED: "已關閉",
}

/** 再開課送出的新起訖時間（US11 / #288）——兩者皆必填，對齊後端 `ReopenCourseReq`。 */
export interface ReopenPayload {
  open_start_at: string
  open_end_at: string
  version: number
}

/**
 * 關閉 / 再開課之結果（對齊後端 `CourseStatusResult`）。
 *
 * ⚠️ `closed_at` **再開課後仍會帶值**（FR-ET-US11-10：保留供追溯），故不可用
 * 「有沒有值」判斷課程是否關閉中——那要看 `status`。
 */
export interface CourseStatusResult {
  course_id: number
  status: string
  open_start_at: string | null
  open_end_at: string | null
  closed_at: string | null
  version: number
}

// ── 表單驗證（Zod）────────────────────────────────────────────────────────────

import { z } from "zod"

/**
 * ET05 基本資料表單驗證，命名對齊後端 Pydantic `CourseCreateReq` / `CourseUpdateReq`。
 *
 * **僅課程名稱必填**——受訓單位標籤與起訖時間為「發布時」必填（FR-ET-US3-01），
 * 發布檢核屬 #204，本表單不檢核。
 */
export const CourseFormSchema = z.object({
  course_name: z
    .string()
    .trim()
    .min(1, { message: "請輸入課程名稱" })
    .max(COURSE_NAME_MAX_LEN, { message: `課程名稱不可超過 ${COURSE_NAME_MAX_LEN} 字元` }),
  description: z
    .string()
    .trim()
    .max(DESCRIPTION_MAX_LEN, { message: `課程描述不可超過 ${DESCRIPTION_MAX_LEN} 字` }),
  require_approval: z.boolean(),
})

export type CourseFormValues = z.infer<typeof CourseFormSchema>

/** 章節名稱驗證，對齊後端 `ChapterCreateReq`。 */
export const ChapterNameSchema = z
  .string()
  .trim()
  .min(1, { message: "請輸入章節名稱" })
  .max(CHAPTER_NAME_MAX_LEN, { message: `章節名稱不可超過 ${CHAPTER_NAME_MAX_LEN} 字元` })


/** ET01 課程列表的一張卡片（對齊後端 `CourseCard`）。 */
export interface CourseCard {
  course_id: number
  course_name: string
  status: "DRAFT" | "PUBLISHED" | "CLOSED"
  open_start_at: string | null
  open_end_at: string | null
  owner_id: string
  /** 取自 `DP_USER`；**查無此人**（資料不一致）時為 `null`。帳號停用時仍回姓名。 */
  owner_name: string | null
  /**
   * 建立者帳號是否已停用（#330）。用 `ownerLabel()` 組字串，不要各頁自己拼。
   *
   * 來源是後端的 `DP_USER.STATUS`——**不是** `DELETED`（EDMS 沒有刪除使用者的功能，
   * 那個欄位恆為 0）。
   */
  owner_is_disabled: boolean
  /** 卡片 badges；`label` 由後端組好（「全單位」省略）。 */
  audiences: AudiencePair[]
  chapter_count: number
  /** **在籍**學員數——已移除者不計入。 */
  student_count: number
  /**
   * 由**後端**判定，決定「檢視」標籤與進入模式。
   *
   * 前端不可自行比對 `owner_id` 與當前使用者——那等於把授權語意複製一份到瀏覽器，
   * 而那一份遲早與後端分岔。
   */
  is_owner: boolean
  /**
   * 是否**視同關閉**——「已關閉」或「已發布但閱課期間已過」皆為 `true`。
   *
   * ⚠️ 狀態 pill 看這個欄位，**不要自己判 `status`**：期間已過時 `status` 仍是
   * `PUBLISHED`（到期自動轉 `CLOSED` 屬未實作的 ET-16），自行判定會標成「已發布」，
   * 而學員其實早已進不去。
   */
  is_closed: boolean
}

/**
 * 課程列表查詢條件。`scope` 決定狀態過濾，兩者相反（見後端 `build_list_stmt`）。
 *
 * ⚠️ **這是與後端共用的契約**。欄位集合有兩條互相指名的測試：前端
 * `CourseListPage.test.tsx`「送出的查詢參數恰為契約所列」、後端
 * `test_et_course_list.py::test_前端送出的完整參數集合可通過後端驗證`。改這裡要一起改。
 */
export interface CourseListParams {
  scope: "mine" | "all"
  /** 後端 `Query(max_length=100)`；輸入框以 `KEYWORD_MAX_LENGTH` 卡住同一個上限。 */
  q?: string
  /** 職位；與 `unit_tag_id` 皆比對課程配對的**字面值**、不展開通用值（#538 SA Q2）。 */
  tag_id?: number
  /** 單位；與 `tag_id` 並用時須同一組配對同時符合。 */
  unit_tag_id?: number
  owner_id?: string
  page?: number
  limit?: number
}

/** 關鍵字長度上限，對齊後端 `Query(max_length=100)`。兩邊必須一起改。 */
export const KEYWORD_MAX_LENGTH = 100

/**
 * 建立者顯示字串——**三個畫面共用同一支**（#330）。
 *
 * 修正前卡片顯示「—」、建立者下拉顯示 `owner_id`、詳細頁顯示姓名，同一個人三種身份。
 * 根因是三處各自寫 fallback。集中在這裡，下一個要顯示建立者的地方就不必再決定一次。
 *
 * 三種狀態刻意分開：
 * - 正常 → `王大明`
 * - 帳號已停用 → `王大明（已停用帳號）`——代表沒有人能編輯這門課、需要交接
 * - `owner_name === null` → `—`，代表 `DP_USER` 查無此列（資料不一致），與停用是兩回事
 *
 * 不回傳 `owner_id`：它是 `uuid4().hex[:20]` 的隨機代理鍵（登入帳號是 EMAIL），對使用者
 * 沒有意義，顯示它只會讓畫面出現一串看不懂的字。**這不是一道安全防護**——`owner_id`
 * 本來就在 API 回應與下拉的 DOM 屬性裡，拿掉的只有顯示文字。
 */
export function ownerLabel(owner: { owner_name: string | null; owner_is_disabled: boolean }): string {
  if (owner.owner_name === null) return "—"
  return owner.owner_is_disabled ? `${owner.owner_name}（已停用帳號）` : owner.owner_name
}
