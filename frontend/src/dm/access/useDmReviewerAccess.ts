import { useQuery } from "@tanstack/react-query"

import { dmReviewerAccessApi } from "./reviewerAccessService"

/**
 * DM 審核者入口可見性（具 DM_REVIEWER，#250）。供側欄逐項閘「簽核中心」。
 * `enabled` 於側欄僅在「具任一 DM 角色」時開啟，避免非 DM 使用者觸發 403；
 * 比照 `useDmAdminAccess`。
 */
export function useDmReviewerAccess(enabled = true) {
  return useQuery({
    queryKey: ["dm", "reviewer-access"],
    queryFn: dmReviewerAccessApi.get,
    enabled,
  })
}
