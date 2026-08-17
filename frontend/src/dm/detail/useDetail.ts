import { useQuery } from "@tanstack/react-query"

import { detailApi } from "./detailService"

/** 文件詳細（目前發布版）。 */
export function useDetail(docId: string) {
  return useQuery({ queryKey: ["dm-detail", docId], queryFn: () => detailApi.getDetail(docId), enabled: !!docId })
}

/** 版本歷程（僅在展開時抓取）。 */
export function useVersions(docId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dm-detail", docId, "versions"],
    queryFn: () => detailApi.getVersions(docId),
    enabled: !!docId && enabled,
  })
}