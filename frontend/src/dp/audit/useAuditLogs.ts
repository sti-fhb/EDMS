import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { auditApi } from "./auditService"
import type { AuditFilterParams, AuditLogRow } from "./auditService"

const DEFAULT_LIMIT = 20

/** 查詢列輸入值（空字串＝未指定）。 */
export interface AuditFilters {
  operator: string
  module: string
  action_type: string
  result: string
  date_from: string
  date_to: string
}

export const EMPTY_AUDIT_FILTERS: AuditFilters = {
  operator: "",
  module: "",
  action_type: "",
  result: "",
  date_from: "",
  date_to: "",
}

/** 空字串欄位轉 undefined，避免帶入無意義 query string。 */
function toParams(f: AuditFilters): AuditFilterParams {
  return {
    operator: f.operator || undefined,
    module: f.module || undefined,
    action_type: f.action_type || undefined,
    result: f.result || undefined,
    date_from: f.date_from || undefined,
    date_to: f.date_to || undefined,
  }
}

/** 操作記錄查詢頁狀態（多條件查詢 / 後端分頁 / 明細檢視 / CSV 匯出）。 */
export function useAuditLogs() {
  const { message } = useNotification()
  // 已送出的查詢（與輸入分離：按「查詢」才套用；匯出亦以此為準，確保與畫面一致）
  const [query, setQuery] = useState({ ...EMPTY_AUDIT_FILTERS, page: 1, limit: DEFAULT_LIMIT })
  const [selected, setSelected] = useState<AuditLogRow | null>(null)
  const [exporting, setExporting] = useState(false)

  const { data, isPending } = usePagedQuery(QUERY_KEYS.audit.list(query), () =>
    auditApi.list({ ...toParams(query), page: query.page, limit: query.limit }),
  )

  const search = useCallback((filters: AuditFilters) => {
    setQuery((prev) => ({ ...prev, ...filters, page: 1 }))
  }, [])

  const setPage = useCallback((page: number) => setQuery((prev) => ({ ...prev, page })), [])

  const exportCsv = useCallback(async () => {
    setExporting(true)
    try {
      const blob = await auditApi.exportCsv(toParams(query))
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = "audit_log.csv"
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      message.error(toApiError(err).errorMessage)
    } finally {
      setExporting(false)
    }
  }, [query, message])

  return {
    items: data?.data ?? [],
    total: data?.meta?.total ?? 0,
    loading: isPending,
    page: query.page,
    limit: query.limit,
    setPage,
    search,
    selected,
    setSelected,
    exportCsv,
    exporting,
  }
}
