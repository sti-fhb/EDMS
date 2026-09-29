/** 文件新增與編輯（US5 / DM03）型別與表單驗證（對齊後端 app/dm/editor/schemas.py）。 */

import { z } from "zod"

/** 表單受控下拉項。 */
export interface OptionItem {
  code: string // 分類碼 / func_code / 標籤 TAG_ID 字串
  name: string
  group_code?: string | null // 檢索標籤所屬組（MODULE / NATURE / LEGAL）
}

/** DM03 表單一次載入之受控下拉集合。 */
export interface EditorOptions {
  categories: OptionItem[]
  funcs: OptionItem[]
  audiences: OptionItem[] // 可見對象之職位（含通用值「全體」）
  units: OptionItem[] // 可見對象之單位（含通用值「全單位」＝不限單位，#437）
  retrieval_tags: OptionItem[]
}

/**
 * 可見對象之 (單位, 職位) 配對（#437）。
 *
 * 文件掛 [(軍醫局, 護理師), (三總, 行政人員)] 意為「僅此兩種人」——不含「軍醫局的行政人員」
 * 與「三總的護理師」。故兩欄必須成對設定，不可拆成兩個獨立多選。
 */
export interface AudiencePair {
  unit_id: string
  audience_id: string
}

/** 指定審核者下拉項（具 DM_REVIEWER 角色、排除自己）。 */
export interface ReviewerItem {
  user_id: string
  user_name: string
}

/** 文件現有標籤，供編輯模式預帶可改。 */
export interface EditorDocTags {
  audience_pairs: AudiencePair[]
  retrieval_ids: string[]
}

/** 新增草稿文件結果。 */
export interface CreateResult {
  doc_id: string
  version_id: number
  previewable: boolean
}

/** 新增草稿版本結果。 */
export interface VersionResult {
  version_id: number
  previewable: boolean
}

/** 送簽結果。 */
export interface SubmitResult {
  review_id: number
  notified: number
}

/**
 * 續編草稿之編輯器 meta（author-scoped；供 DRAFT-status 文件亦可載，對齊後端 DraftMeta）。
 * `doc_status==="DRAFT"`（首版草稿）→ `name_editable=true`（名稱可改，Q1=A）；`PUBLISHED`（新版本草稿）→ 唯讀。
 */
export interface DraftMeta {
  doc_id: string
  doc_name: string
  category_code: string
  category_name: string
  func_code: string | null
  func_name: string | null
  doc_status: string
  name_editable: boolean
  draft_version_id: number
  version_no: string | null
  change_summary: string | null
  file_name: string | null
  file_size: number | null
  previewable: boolean
  assigned_reviewer: string | null
}

/** 系統操作手冊分類代碼（選此分類才顯示 / 必填關聯作業項目 func）。 */
export const MANUAL_CATEGORY = "MANUAL"
/** 訓練教材：由教育訓練模組引用，不設定可見對象（#377，spec_us5 FR-009 之例外）。 */
export const TRAINING_CATEGORY = "TRAINING"

/** 單一 (單位, 職位) 配對之驗證；兩欄皆必選。 */
const AudiencePairSchema = z.object({
  unit_id: z.string().min(1, { message: "請選擇單位" }),
  audience_id: z.string().min(1, { message: "請選擇職位" }),
})

/** 可內嵌預覽之 MIME（其餘如 Office 上傳時出橘色警示條 DM-MSG-DM03-002）。 */
const PREVIEWABLE_MIMES = new Set(["application/pdf", "image/png", "image/jpeg", "image/jpg", "image/gif"])

/** 檔案是否可線上預覽（PDF / 圖片）；Office 等回 false。 */
export function isPreviewableMime(mime: string): boolean {
  return PREVIEWABLE_MIMES.has(mime.toLowerCase())
}

/** 表單狀態（新增 / 編輯共用；編輯模式身份欄與標籤唯讀、不送出）。 */
export interface EditorForm {
  doc_name: string
  category_code: string
  func_code: string
  audience_pairs: AudiencePair[] // 可見對象 (單位, 職位) 配對
  retrieval_ids: string[] // 檢索標籤 TAG_ID 字串（僅新增模式使用）
  version_no: string
  change_summary: string
  reviewer_id: string // 送簽時必填
}

export const EMPTY_EDITOR_FORM: EditorForm = {
  doc_name: "",
  category_code: "",
  func_code: "",
  audience_pairs: [],
  retrieval_ids: [],
  version_no: "",
  change_summary: "",
  reviewer_id: "",
}

/**
 * 依模式 / 分類 / 動作動態建構表單 schema。
 * - 新增模式：doc_name / category 必填；MANUAL 時 func 必填。
 * - **存草稿（forSubmit=false）不卡必填**：名稱 / 版號 / 摘要 / 可見對象 / func 皆可空（新增模式僅
 *   分類必填——DOC_ID 配號用）；檔案於呼叫端另處理（草稿可不附）。
 * - **送簽（forSubmit=true）** 完整檢核：名稱（新增）/ 版號 / 摘要 / 可見對象 ≥1 / 審核者 /（MANUAL）func。
 * - **TRAINING 免填可見對象**（#377）：教材由 ET 引用、ET 取教材不套可見性條件，故不檢核。
 */
export function makeEditorSchema(opts: {
  isNew: boolean
  isManual: boolean
  forSubmit: boolean
  isTraining?: boolean // TRAINING 分類：可見對象免填
  requireName?: boolean // 續編首版草稿（名稱可改）送簽時亦要求名稱
}) {
  const { isNew, isManual, forSubmit, isTraining = false, requireName = false } = opts
  return z
    .object({
      doc_name:
        (isNew || requireName) && forSubmit ? z.string().trim().min(1, { message: "請輸入文件名稱" }) : z.string(),
      // 分類為新增模式之結構必填（DOC_ID 配號用），草稿亦需
      category_code: isNew ? z.string().min(1, { message: "請選擇分類" }) : z.string(),
      func_code: z.string(),
      version_no: forSubmit ? z.string().trim().min(1, { message: "請輸入版本號" }) : z.string(),
      change_summary: forSubmit ? z.string().trim().min(1, { message: "請輸入變更摘要" }) : z.string(),
      // 配對兩欄皆必填：漏填單位不會變成「不限」，而是一組不生效的配對（後端 visibility 亦然）
      audience_pairs:
        forSubmit && !isTraining
          ? z.array(AudiencePairSchema).min(1, { message: "請至少指定 1 組可見對象" })
          : z.array(AudiencePairSchema),
      retrieval_ids: z.array(z.string()),
      reviewer_id: forSubmit ? z.string().min(1, { message: "請指定審核者" }) : z.string(),
    })
    .superRefine((val, ctx) => {
      if (forSubmit && isNew && isManual && !val.func_code) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["func_code"], message: "請選擇關聯作業項目" })
      }
    })
}