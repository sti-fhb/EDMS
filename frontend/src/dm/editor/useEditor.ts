import { useQuery } from "@tanstack/react-query"

import { editorApi } from "./editorService"
import { QUERY_KEYS } from "../../constants/queryKeys"

/** DM08 表單受控下拉（分類 / func / 可見對象 / 檢索標籤）。 */
export function useEditorOptions() {
  return useQuery({ queryKey: ["dm-editor", "options"], queryFn: editorApi.getOptions })
}

/** 指定審核者下拉（具 DM_REVIEWER 角色、排除自己）。 */
export function useReviewers() {
  return useQuery({ queryKey: ["dm-editor", "reviewers"], queryFn: editorApi.listReviewers })
}

/** 編輯模式預帶：文件現有可見對象 / 檢索標籤（僅編輯模式啟用）。 */
export function useDocTags(docId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dm-editor", "doc-tags", docId],
    queryFn: () => editorApi.getDocTags(docId),
    enabled: enabled && !!docId,
  })
}

/** 續編模式 meta（author-scoped）：有本人草稿回 DraftMeta、無則 null（改走加新版）；僅編輯模式啟用。 */
export function useDraftMeta(docId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dm-editor", "draft-meta", docId],
    queryFn: () => editorApi.getDraftMeta(docId),
    enabled: enabled && !!docId,
  })
}
/**
 * 上傳限制（#455）。供上傳說明與 `accept` 使用。
 *
 * ⚠️ **載入中與失敗時呼叫端必須停用上傳輸入**，不可退回「不設 `accept`」——那是
 * 放寬（從受限清單變成全部檔案）。寧可暫時不能選，也不要讓使用者選到一個必定被
 * 後端退回的檔案。
 */
export function useUploadLimits() {
  return useQuery({ queryKey: QUERY_KEYS.dmEditor.uploadLimits(), queryFn: editorApi.getUploadLimits })
}
