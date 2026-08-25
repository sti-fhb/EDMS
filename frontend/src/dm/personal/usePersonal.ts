import { useQuery } from "@tanstack/react-query"

import { personalApi } from "./personalService"

/** 草稿匣（本人 DRAFT 版本，三類）。 */
export function useDrafts() {
  return useQuery({ queryKey: ["dm-personal", "drafts"], queryFn: personalApi.listDrafts })
}

/** 我的文件動態（近 30 天、角色視角）。 */
export function useActivity() {
  return useQuery({ queryKey: ["dm-personal", "activity"], queryFn: personalApi.getActivity })
}

/**
 * 個人專區入口可見性（具編輯者或審核者）。供側欄閘個人專區單項（SA 裁示 Q1=C）。
 * `enabled` 於側欄僅在「具任一 DM 角色」時開啟，避免非 DM 使用者觸發 403。
 */
export function usePersonalAccess(enabled = true) {
  return useQuery({
    queryKey: ["dm-personal", "access"],
    queryFn: personalApi.getAccess,
    enabled,
  })
}
