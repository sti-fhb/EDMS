import { useQuery } from "@tanstack/react-query"

import { detailApi } from "./detailService"

/** 文件詳細（目前發布版）。enabled 供呼叫端停用（如編輯器續編首版草稿時，父文件 DRAFT 不對外瀏覽會 404）。 */
export function useDetail(docId: string, enabled = true) {
  return useQuery({
    queryKey: ["dm-detail", docId],
    queryFn: () => detailApi.getDetail(docId),
    enabled: !!docId && enabled,
  })
}

/** 版本歷程（僅在展開時抓取）。 */
export function useVersions(docId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dm-detail", docId, "versions"],
    queryFn: () => detailApi.getVersions(docId),
    enabled: !!docId && enabled,
  })
}