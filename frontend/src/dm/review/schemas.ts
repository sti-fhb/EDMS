/** 簽核處理（US6 / DM02）型別與表單驗證（對齊後端 app/dm/review/schemas.py）。 */

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
  category_name: string | null // 分類中文名（清單顯示用）
  review_type: string // NEW / NEW_VERSION / OBSOLETE
  version_no: string | null
  submitter_id: string
  submitter_name: string | null
  submit_date: string
  waiting_days: number
  /** 是否逾催辦門檻 → 清單標紅（FR-006）。**由後端判定**，見下方刪除常數的理由。 */
  overdue: boolean
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
  category_name: string | null // 分類中文名（顯示用；category_code 為英文碼）
  // 本次送審之標籤（#377）：新增／新版本為該版本快照、廢止為文件層現值。供審核者核對可見對象。
  audience_tags: string[]
  retrieval_tags: string[]
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

// ⚠️ 原本此處有 `REMIND_THRESHOLD_DAYS = 7`，已於 #503 移除。
// 催辦門檻是管理者可在 DP 後台調整的 `DP_PARAM.DM_REMIND_THRESHOLD`（值域 1–30），
// 前端寫死會與實際催辦行為脫鉤——門檻調成 3 時系統每天寄信、畫面卻要第 7 天才標紅。
// 改由後端在 `PendingItem.overdue` 給答案，門檻不過線就不會再分家。
//
// ⚠️ 上句的「系統每天寄信」寫於 #503，但**當時是假的**：`AUTO_REMIND` 的 CHANNEL 是 `MSG`，
// 催辦從 2026-08-06 到 2026-10-14 一封都沒寄過（#627）。自 #627 改為 `EMAIL` 後才成立。
// 留著這段註記是因為上面那個論證**不依賴寄不寄信**——即使真的不寄，前端寫死門檻仍會與
// 後端標紅的那條線分家；但讀者不該以為「每天寄信」這件事一直都是真的。

/** 送審狀態顯示名（一律中文；#8 詞彙統一）。 */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  PENDING: "待審核",
  APPROVED: "已核准",
  REJECTED: "已退回",
  WITHDRAWN: "已撤回",
}

/** 送審狀態顯示名（無對應時回中文「未知狀態」，不外顯英文代碼）。 */
export function reviewStatusLabel(status: string): string {
  return REVIEW_STATUS_LABELS[status] ?? "未知狀態"
}
