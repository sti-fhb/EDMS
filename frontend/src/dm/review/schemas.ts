/** 簽核處理（US6 / DM04）型別與表單驗證（對齊後端 app/dm/review/schemas.py）。 */

import { z } from "zod"

/** 退回原因表單驗證（必填非空；後端另有 max_length 500）。 */
export const RejectReqSchema = z.object({
  reason: z.string().trim().min(1, { message: "請填寫退回原因" }),
})

export interface PendingItem {
  review_id: number
  doc_id: string
  doc_name: string
  category_code: string
  review_type: string // NEW / NEW_VERSION / OBSOLETE
  version_no: string | null
  submitter_id: string
  submitter_name: string | null
  submit_date: string
  waiting_days: number
}

export interface VersionMeta {
  version_id: number
  version_no: string | null
  file_name: string | null
  file_size: number | null
  file_mime: string | null
  previewable: boolean
}

export interface ReviewDetail {
  review_id: number
  doc_id: string
  doc_name: string
  category_code: string
  review_type: string
  change_summary: string | null
  submit_date: string
  submitter_id: string
  submitter_name: string | null
  new_version: VersionMeta | null
  current_version: VersionMeta | null // 新版本申請附目前發布版供比對；首版為 null
  obsolete_reason: string | null // 廢止原因（OBSOLETE）
  obsolete_file_name: string | null // 廢止附件檔名（OBSOLETE；有則可下載）
  obsolete_file_size: number | null // 廢止附件大小（位元組）
}

export interface CompletedItem {
  review_id: number
  doc_id: string
  doc_name: string
  review_type: string
  status: string // APPROVED / REJECTED
  version_no: string | null
  complete_date: string | null
}

export interface ApproveResult {
  published_version_id: number
  notified: number
}

export interface RejectResult {
  review_id: number
}

/** 送審類型顯示名。 */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  NEW: "新增",
  NEW_VERSION: "新版本",
  OBSOLETE: "廢止",
}

/** 停留天數標紅門檻（與後端 DM_REMIND_THRESHOLD 預設一致；逾此於清單標紅警示）。 */
export const REMIND_THRESHOLD_DAYS = 7

/** 已完成狀態顯示名。 */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  APPROVED: "已核准",
  REJECTED: "已退回",
}
