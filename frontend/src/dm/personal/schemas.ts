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

/** 一筆狀態變動事件（一次送審週期展開為 送審 → 結果 多筆事件；時間新→舊）。 */
export interface ActivityEvent {
  review_id: number
  doc_id: string
  doc_name: string
  review_type: string // NEW / NEW_VERSION / OBSOLETE
  status: string // PENDING / APPROVED / REJECTED / WITHDRAWN
  event_kind: "submitted" | "resolved" // 送審(發起廢止) / 結果(核准 退回 撤回)
  event_time: string
  is_overdue: boolean // 僅 PENDING 之 submitted 事件；審核者視角逾門檻顯「催辦中」
  party_name: string | null // 撰寫者視角＝指定審核者；審核者視角＝送審者
}

/** 文件廢止通知一筆（他人對本人有版本之文件發起廢止）。 */
export interface ObsoleteNotice {
  review_id: number
  doc_id: string
  doc_name: string
  status: string // PENDING（廢止待簽核）/ APPROVED（已廢止）
  initiator_name: string | null // 廢止發起人
  reviewer_name: string | null // 廢止審核者
  event_time: string
}

export interface ActivityResponse {
  author: ActivityEvent[]
  reviewer: ActivityEvent[]
  obsolete_notices: ObsoleteNotice[]
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

/** 送審類型顯示名（動態「類型」欄）。 */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  NEW: "新增",
  NEW_VERSION: "新版本",
  OBSOLETE: "廢止",
}

type Tone = "warning" | "success" | "error" | "default"

/** 事件標籤 + Chip 色調（一律中文；#8 詞彙統一，無英文 fallback）。 */
export interface EventLabel {
  text: string
  tone: Tone
}

/**
 * 撰寫者視角事件標籤：
 * - 送審中（submitted 尚 PENDING）→ 廢止則「廢止待簽核」
 * - 送審 / 發起廢止（submitted 且該週期已完成，作為歷程起點）
 * - 核准發布 / 已廢止 / 已退回 / 已撤回（resolved）
 */
export function authorEventLabel(e: {
  review_type: string
  status: string
  event_kind: string
}): EventLabel {
  const isObsolete = e.review_type === "OBSOLETE"
  if (e.event_kind === "resolved") {
    if (e.status === "APPROVED") return { text: isObsolete ? "已廢止" : "核准發布", tone: "success" }
    if (e.status === "REJECTED") return { text: "已退回", tone: "error" }
    return { text: "已撤回", tone: "default" } // WITHDRAWN
  }
  // submitted
  if (e.status === "PENDING") return { text: isObsolete ? "廢止待簽核" : "送審中", tone: "warning" }
  return { text: isObsolete ? "發起廢止" : "送審", tone: "default" } // 已完成週期之送審起點
}

/**
 * 審核者視角事件標籤（後端已使審核者視角一次送審至多一列：待辦或最終結果，無歷史「收到送審」列）：
 * - 待處理 / 待處理（廢止）/ 催辦中（PENDING 待辦）
 * - 已核准 / 已核准廢止 / 已退回 / 已被撤回（resolved 結果）
 */
export function reviewerEventLabel(e: {
  review_type: string
  status: string
  event_kind: string
  is_overdue: boolean
}): EventLabel {
  const isObsolete = e.review_type === "OBSOLETE"
  if (e.event_kind === "resolved") {
    if (e.status === "APPROVED") return { text: isObsolete ? "已核准廢止" : "已核准", tone: "success" }
    if (e.status === "REJECTED") return { text: "已退回", tone: "error" }
    return { text: "已被撤回", tone: "default" } // WITHDRAWN
  }
  // submitted（審核者視角只有 PENDING 待辦會到這）
  if (e.is_overdue) return { text: "催辦中", tone: "error" }
  return { text: isObsolete ? "待處理（廢止）" : "待處理", tone: "warning" }
}

/** 文件廢止通知狀態標籤（僅廢止待簽核 / 已廢止兩態）。 */
export function obsoleteNoticeLabel(status: string): EventLabel {
  if (status === "APPROVED") return { text: "已廢止", tone: "error" }
  return { text: "廢止待簽核", tone: "warning" } // PENDING
}
