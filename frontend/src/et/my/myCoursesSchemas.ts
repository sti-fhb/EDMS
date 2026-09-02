/** ET04 我的課程與加入新課程型別與表單驗證（對齊後端 `app/et/enrollment/schemas.py`）。 */

import { z } from "zod"

/** 邀請碼長度（`ET_COURSE.INVITATION_CODE` 為 `VARCHAR(8)`）。 */
export const INVITATION_CODE_LENGTH = 8

/**
 * 邀請碼：8 碼純數字（AC 5）。
 *
 * 後端仍會以 `rules.normalize_invitation_code` 再驗一次——前端擋下只是讓使用者在
 * 按下查詢前就知道「還差兩碼」，不是把關。
 *
 * 以 `[0-9]` 而非 `\d`：JS 的 `\d` 在未加 `u` flag 時雖等同 `[0-9]`，寫死 ASCII
 * 區間可與後端的 ASCII-only 判定對齊，也避免日後有人加上 `u` flag 後語意悄悄改變。
 */
export const invitationCodeSchema = z
  .string()
  .trim()
  .regex(new RegExp(`^[0-9]{${INVITATION_CODE_LENGTH}}$`), `邀請碼為 ${INVITATION_CODE_LENGTH} 碼數字`)

/** 課程狀態（對齊後端 `ET_COURSE_STATUS`）。學員端只會見到後兩者。 */
export type CourseStatus = "DRAFT" | "PUBLISHED" | "CLOSED"

/** 完課狀態（對齊後端 `ET_COMPLETION_STATUS`）。 */
export type CompletionStatus = "NOT_STARTED" | "IN_PROGRESS" | "COMPLETED"

export const COMPLETION_STATUS_LABEL: Record<CompletionStatus, string> = {
  NOT_STARTED: "未開始",
  IN_PROGRESS: "進行中",
  COMPLETED: "已完成",
}

export interface MyCourseRow {
  course_id: number
  course_name: string
  status: CourseStatus
  completion_status: CompletionStatus
  tags: string[]
  chapter_count: number
  open_start_at: string | null
  open_end_at: string | null
  /** **本 issue 恆為 0**——進度累積依賴 `ET_PROGRESS`，屬 `ET-5`。 */
  progress_pct: number
}

export interface MyCoursesSummary {
  joined: number
  in_progress: number
  not_started: number
  completed: number
}

export interface MyCoursesResult {
  summary: MyCoursesSummary
  courses: MyCourseRow[]
}

export interface JoinPreview {
  course_id: number
  course_name: string
  owner_name: string | null
  chapter_count: number
  /** 已加入——**非錯誤**，前端據此直接導向該課程（AC 10）。 */
  already_joined: boolean
  /** 課程開放學習之時間；未到時仍可加入（SA Q2 裁示 A），用於提示文案。 */
  open_start_at: string | null
}

export interface JoinResult {
  course_id: number
  completion_status: CompletionStatus
  /** 加入當下課程尚未開放——提示改為「課程開放後將出現於清單」。 */
  pending_open: boolean
}
