import { useQuery } from "@tanstack/react-query"

import { libraryApi } from "./libraryService"
import type { SearchParams } from "./libraryService"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 文件庫搜尋（後端分頁）。 */
export function useLibrarySearch(params: SearchParams) {
  return usePagedQuery(["dm-library", "documents", params], () => libraryApi.search(params))
}

/** func_name 下拉（僅「系統操作手冊」分類需要時才啟用）。 */
export function useFuncOptions(enabled: boolean) {
  return useQuery({ queryKey: ["dm-library", "func-options"], queryFn: libraryApi.funcOptions, enabled })
}

/** 檢索標籤下拉（不含可見對象）。 */
export function useRetrievalTags() {
  return useQuery({ queryKey: ["dm-library", "retrieval-tags"], queryFn: libraryApi.retrievalTags })
}

/** 當前使用者操作能力（新增文件入口顯示與否）。 */
export function useLibraryCapabilities() {
  return useQuery({ queryKey: ["dm-library", "capabilities"], queryFn: libraryApi.capabilities })
}