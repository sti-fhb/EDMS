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
  /**
   * 對學員**視同關閉**（#288）：`status === "CLOSED"` **或**「已發布但閱課期間已過」。
   *
   * ⚠️ 卡片的「已關閉」標示看本欄，**不要自己判 `status === "CLOSED"`**——期間已過者
   * 的 `status` 仍是 `PUBLISHED`（到期自動轉 `CLOSED` 屬 `ET-16`、未實作），只看
   * `status` 會讓卡片標「已發布」而點進去 ET05 卻是唯讀的。與 ET05 的
   * `LearnStructure.is_closed` 同名同義。
   */
  is_closed: boolean
  /**
   * 已加入但**閱課起始時間未到**（#363）。卡片據此改為不可點擊並標開放時點。
   *
   * 與 `is_closed` 對稱：兩者都是「列在清單上但不可學習」，一個在期間前、一個在期間後。
   *
   * ⚠️ **不要自己拿 `open_start_at` 跟 `Date.now()` 比**——那會讓判定在後端與前端各有
   * 一份，而瀏覽器時鐘可被使用者改。一律看本欄。
   */
  is_pending_open: boolean
  completion_status: CompletionStatus
  tags: string[]
  chapter_count: number
  open_start_at: string | null
  open_end_at: string | null
  /** 學習進度百分比＝完成項目數 ÷ 總項目數（#274 填實；原為恆 0 的接點）。 */
  progress_pct: number
}

export interface MyCoursesSummary {
  joined: number
  in_progress: number
  not_started: number
  completed: number
  /**
   * 已加入但課程尚未開放的門數（#363）。
   *
   * ⚠️ **與 `not_started` 是兩件事。** `not_started` 是「已開放、還沒開始學」，本欄是
   * 「還沒開放」——學員此刻不可能開始學。合併顯示會讓「未開始」同時指兩件事，而學員
   * 能做的事完全不同（一個是去上課、一個是等）。
   *
   * `joined === in_progress + not_started + completed + pending_open`。
   */
  pending_open: number
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
