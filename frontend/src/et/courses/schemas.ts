/** ET02 課程骨架與章節編排型別（對齊後端 app/et/course/schemas.py）。 */

/** 課程描述長度上限——與後端 `DESCRIPTION_MAX_LEN` 同步（spec_us3 AC 1「至多 500 字」）。 */
export const DESCRIPTION_MAX_LEN = 500
export const COURSE_NAME_MAX_LEN = 100
export const CHAPTER_NAME_MAX_LEN = 100

export interface ChapterItem {
  chapter_id: number
  chapter_name: string
  sort_order: number
  version: number
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

export interface CoursePayload {
  course_name: string
  description: string | null
  open_start_at: string | null
  open_end_at: string | null
  require_approval: boolean
  tag_ids: number[]
}

/** 課程狀態（ET_COURSE_STATUS）。本 issue 僅寫入 DRAFT；發布屬 #204。 */
export const COURSE_STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  PUBLISHED: "已發布",
  CLOSED: "已關閉",
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
  open_start_at: z.string(),
  open_end_at: z.string(),
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
