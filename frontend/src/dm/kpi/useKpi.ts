import { kpiApi } from "./kpiService"
import type { KpiSearchParams } from "./kpiService"
import type { KpiDocItem, KpiListResponse } from "./schemas"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/**
 * 閱讀統計 KPI 查詢（後端分頁）。`enabled`：僅在確認具管理者權限後才發（避免非管理者觸發 403 噪音）。
 *
 * 回應為分頁清單 + `summary`（統計卡）；沿用 `usePagedQuery` 包裝（統一 loading/invalidate），
 * 再將 `data` 標註回含 `summary` 之 `KpiListResponse`。
 */
export function useKpiSearch(params: KpiSearchParams, options?: { enabled?: boolean }) {
  const q = usePagedQuery<KpiDocItem>(["dm-kpi", "documents", params], () => kpiApi.search(params), options)
  return q as Omit<typeof q, "data"> & { data: KpiListResponse | undefined }
}
