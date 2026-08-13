/** 文件詳細頁瀏覽（US4 / DM02）型別（對齊後端 app/dm/detail/schemas.py）。 */

export interface FileMeta {
  version_id: number
  file_name: string
  file_mime: string
  file_size: number
  uploaded_at: string | null
  previewable: boolean
}

export interface ObsoleteInfo {
  obsolete_time: string | null
  applicant_id: string
  applicant_name: string | null
  approver_name: string | null
  reason: string | null
  has_attachment: boolean
}

export interface DetailResponse {
  doc_id: string
  doc_name: string
  status: string // PUBLISHED / PENDING_OBSOLETE / OBSOLETE
  current_version_no: string | null
  category_code: string
  category_name: string
  author_id: string
  author_name: string | null
  published_date: string | null
  approver_id: string | null
  approver_name: string | null
  approve_time: string | null
  tags: string[]
  func_code: string | null
  func_name: string | null
  file: FileMeta | null
  can_edit: boolean
  is_obsolete: boolean
  obsolete_info: ObsoleteInfo | null
}

export interface VersionItem {
  version_id: number
  version_no: string
  change_summary: string
  author_id: string
  author_name: string | null
  approver_name: string | null
  published_date: string | null
  is_current: boolean
  previewable: boolean
}

/** 文件狀態碼 → 中文（標題列狀態 pill）。 */
export const DOC_STATUS_LABELS: Record<string, string> = {
  PUBLISHED: "已發布",
  PENDING_OBSOLETE: "廢止待簽核",
  OBSOLETE: "已廢止",
}