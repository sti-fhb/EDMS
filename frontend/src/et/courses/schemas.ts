/** ET02 課程骨架與章節編排型別（對齊後端 app/et/course/schemas.py）。 */

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
  /** 建立者姓名（唯讀 join DP_USER；查無 null）——檢視模式 banner 用。 */
  owner_name: string | null
  /** 當前使用者是否為擁有者；false 時全頁唯讀（spec.md §擁有權判定）。 */
  is_owner: boolean
  tag_ids: number[]
  chapters: ChapterItem[]
  /** 課程邀請碼；**僅 owner 可見**，非擁有者後端回 null（#247）。 */
  invitation_code: string | null
}

export interface TagOption {
  tag_id: number
  tag_name: string
  /** false 只會出現在「課程既有已掛之停用標籤」——不得再新掛（FR-ET-US3-03）。 */
  is_active: boolean
}

export interface CourseCreateResult {
  course_id: number
  version: number
}

export interface Capabilities {
  /** 具教師角色（SA 裁示 Q2）→ 顯示「新增課程」入口。 */
  can_create_course: boolean
  /** 具教師或管理者角色 → 顯示側欄教學管理項（課程列表 / 學員 / 核可查詢）。 */
  can_manage_courses: boolean
  /** 具學員角色 → 顯示側欄「我的課程」。 */
  can_learn: boolean
}

export interface CoursePayload {
  course_name: string
  description: string | null
  open_start_at: string | null
  open_end_at: string | null
  require_approval: boolean
  tag_ids: number[]
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
 * ET02 基本資料表單驗證，命名對齊後端 Pydantic `CourseCreateReq` / `CourseUpdateReq`。
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
  tag_ids: z.array(z.number()),
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
  /** 取自 `DP_USER`；帳號已刪時為 `null`。 */
  owner_name: string | null
  tags: TagOption[]
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
}

/** 課程列表查詢條件。`scope` 決定狀態過濾，兩者相反（見後端 `build_list_stmt`）。 */
export interface CourseListParams {
  scope: "mine" | "all"
  q?: string
  tag_id?: number
  owner_id?: string
  page?: number
  limit?: number
}
