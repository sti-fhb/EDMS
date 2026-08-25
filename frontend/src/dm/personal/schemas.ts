/** 個人專區（US9 / UCDM09 / DM07）型別（對齊後端 app/dm/personal/schemas.py）。 */

/** 草稿分類（依該版本之 DM_REVIEW 歷史）。 */
export type DraftKind = "unsubmitted" | "rejected" | "withdrawn"

export interface DraftItem {
  version_id: number
  doc_id: string
  doc_name: string
  version_no: string | null
  change_summary: string | null
  category_code: string
  kind: DraftKind
  updated_date: string | null
}

export interface WithdrawResult {
  review_id: number
  doc_status: string
}

export interface ActivityItem {
  review_id: number
  doc_id: string
  doc_name: string
  review_type: string // NEW / NEW_VERSION / OBSOLETE
  status: string // PENDING / APPROVED / REJECTED / WITHDRAWN
  submit_date: string
  complete_date: string | null
}

export interface ActivityResponse {
  author: ActivityItem[]
  reviewer: ActivityItem[]
}

export interface PersonalAccess {
  can_access: boolean
}

/** 草稿分類顯示名。 */
export const DRAFT_KIND_LABELS: Record<DraftKind, string> = {
  unsubmitted: "未送審",
  rejected: "被退回待修改",
  withdrawn: "已撤回",
}

/**
 * 送審事件顯示標籤：由 review_type + status 映射（撰寫者 / 審核者視角共用原始資料，標籤依視角）。
 * 撰寫者視角：送審中 / 核准發布 / 退回 / 廢止待簽核 / 已廢止 / 已撤回。
 */
export function authorEventLabel(review_type: string, status: string): string {
  if (status === "PENDING") return review_type === "OBSOLETE" ? "廢止待簽核" : "送審中"
  if (status === "APPROVED") return review_type === "OBSOLETE" ? "已廢止" : "核准發布"
  if (status === "REJECTED") return "退回"
  if (status === "WITHDRAWN") return "已撤回"
  return status
}

/** 審核者視角：待處理 / 已被撤回 / 已處理（核准 / 退回）。 */
export function reviewerEventLabel(status: string): string {
  if (status === "PENDING") return "待處理"
  if (status === "WITHDRAWN") return "已被撰寫者撤回"
  if (status === "APPROVED") return "已核准"
  if (status === "REJECTED") return "已退回"
  return status
}
