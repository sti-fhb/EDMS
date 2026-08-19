import type {
  CreateResult,
  EditorDocTags,
  EditorOptions,
  ReviewerItem,
  SubmitResult,
  VersionResult,
} from "./schemas"
import { http } from "../../services/http"

/**
 * 文件新增與編輯 API（US5 / DM03，寫入）。
 * 新增 / 加版以 multipart（FormData）送表單欄位 + 單一上傳檔；送簽以 JSON。
 */

/** 新增草稿文件之表單欄位（file 可為 null＝存草稿暫不附檔）。 */
export interface CreateDocPayload {
  doc_name: string
  category_code: string
  func_code: string // 空字串＝不指定（非手冊類）
  audience_ids: string[]
  retrieval_ids: string[]
  version_no: string
  change_summary: string
  file: File | null
}

/** 編輯模式加新版本之表單欄位（身份欄不送；標籤覆寫文件層；file 可為 null＝暫不附檔）。 */
export interface AddVersionPayload {
  version_no: string
  change_summary: string
  audience_ids: string[]
  retrieval_ids: string[]
  file: File | null
}

function buildCreateForm(p: CreateDocPayload): FormData {
  const fd = new FormData()
  fd.append("doc_name", p.doc_name)
  fd.append("category_code", p.category_code)
  if (p.func_code) fd.append("func_code", p.func_code)
  p.audience_ids.forEach((id) => fd.append("audience_ids", id))
  p.retrieval_ids.forEach((id) => fd.append("retrieval_ids", id))
  fd.append("version_no", p.version_no)
  fd.append("change_summary", p.change_summary)
  if (p.file) fd.append("file", p.file)
  return fd
}

export const editorApi = {
  getOptions: async (): Promise<EditorOptions> => {
    const { data } = await http.get<EditorOptions>("/dm/editor/options")
    return data
  },

  listReviewers: async (): Promise<ReviewerItem[]> => {
    const { data } = await http.get<ReviewerItem[]>("/dm/reviewers")
    return data
  },

  createDocument: async (payload: CreateDocPayload): Promise<CreateResult> => {
    const { data } = await http.post<CreateResult>("/dm/documents", buildCreateForm(payload))
    return data
  },

  addVersion: async (docId: string, payload: AddVersionPayload): Promise<VersionResult> => {
    const fd = new FormData()
    fd.append("version_no", payload.version_no)
    fd.append("change_summary", payload.change_summary)
    payload.audience_ids.forEach((id) => fd.append("audience_ids", id))
    payload.retrieval_ids.forEach((id) => fd.append("retrieval_ids", id))
    if (payload.file) fd.append("file", payload.file)
    const { data } = await http.post<VersionResult>(`/dm/documents/${docId}/versions`, fd)
    return data
  },

  getDocTags: async (docId: string): Promise<EditorDocTags> => {
    const { data } = await http.get<EditorDocTags>(`/dm/editor/documents/${docId}/tags`)
    return data
  },

  submit: async (docId: string, body: { version_id: number; assigned_reviewer: string }): Promise<SubmitResult> => {
    const { data } = await http.post<SubmitResult>(`/dm/documents/${docId}/submit`, body)
    return data
  },
}