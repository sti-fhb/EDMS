import { useQuery } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toBlobApiError } from "../../services/http"
import { yesterdayTaipei } from "../../utils/date"
import { auditApi } from "./auditService"
import type { AuditFilterParams, AuditLogRow, AuditOption } from "./auditService"

const DEFAULT_LIMIT = 20

/** 單次匯出筆數上限（#102）。與後端 `query_service.EXPORT_MAX_ROWS` 同值，兩邊須一起改。 */
const EXPORT_MAX_ROWS = 10000

/** 選項未載入時的共用空陣列（見 useAuditOptions 的說明）。 */
const NO_OPTIONS: AuditOption[] = []

/** 查詢列輸入值（空字串＝未指定）。 */
export interface AuditFilters {
  operator: string
  func: string
  action_type: string
  result: string
  date_from: string
  date_to: string
}

/**
 * 查詢列的預設值：起日＝台灣時間的昨天、訖日留空（#926，比照 TBMS DP11）。
 *
 * 不給起日的話，後端 `count_logs()` 會對整張 `DP_AUDIT_LOG` 計數——稽核表只增不減，
 * 一進頁面就得等。給了下界才讓 `IX_DP_AUDIT_LOG_CREATED_DATE` 有範圍可縮。
 *
 * ⚠️ 必須是**函式**，不可改回模組層常數：常數在 import 當下就求值，`vi.setSystemTime()`
 * 是測試 body 裡才呼叫的，屆時值已凍結成真實的昨天、造假時間控制不到它（本檔的
 * 日期測試正是這個寫法）。順帶也讓分頁開著跨過午夜後，清除篩選能取到新的昨天。
 */
export function defaultAuditFilters(): AuditFilters {
  return {
    operator: "",
    func: "",
    action_type: "",
    result: "",
    date_from: yesterdayTaipei(),
    date_to: "",
  }
}

/** 空字串欄位轉 undefined，避免帶入無意義 query string。 */
function toParams(f: AuditFilters): AuditFilterParams {
  return {
    operator: f.operator || undefined,
    func_name: f.func || undefined,
    action_type: f.action_type || undefined,
    result: f.result || undefined,
    date_from: f.date_from || undefined,
    date_to: f.date_to || undefined,
  }
}

/**
 * 篩選下拉選項（來自後端，#477）。
 *
 * 選項是純靜態對照、與稽核資料無關，故設長 `staleTime` 避免每次進頁都重抓；但仍走 query
 * 而非在模組載入時取，因為端點需要授權 header。載入失敗 / 未完成時回空陣列——
 * 下拉會是空的（看得出異常），而非悄悄退回一份可能過期的硬編碼清單。
 */
export function useAuditOptions() {
  const { data } = useQuery({
    queryKey: QUERY_KEYS.audit.options(),
    queryFn: () => auditApi.options(),
    staleTime: 60 * 60 * 1000,
  })
  return {
    // 用模組層常數而非字面 []：後者每次 render 都是新陣列，會讓 AuditPage 的 columns
    // useMemo 在選項載入前每次重算（依賴比對失敗）。
    funcOptions: data?.func_options ?? NO_OPTIONS,
    actionOptions: data?.action_options ?? NO_OPTIONS,
    resultOptions: data?.result_options ?? NO_OPTIONS,
  }
}

/** 操作記錄查詢頁狀態（多條件查詢 / 後端分頁 / 明細檢視 / CSV 匯出）。 */
export function useAuditLogs() {
  const { message } = useNotification()
  // 已送出的查詢（與輸入分離：輸入欄變動後防抖 400ms 才套用，本頁沒有「查詢」按鈕，見
  // AuditPage；匯出亦以此為準，確保與畫面一致）。
  // ⚠️ 初始值與畫面輸入框**兩處**都取自 defaultAuditFilters()：只改畫面那側的話，篩選欄
  // 會顯示昨天、但首次送出的查詢仍不帶 date_from，全表計數照跑而畫面看不出差別（#926）。
  const [query, setQuery] = useState(() => ({ ...defaultAuditFilters(), page: 1, limit: DEFAULT_LIMIT }))
  const [selected, setSelected] = useState<AuditLogRow | null>(null)
  const [exporting, setExporting] = useState(false)

  const { data, isPending } = usePagedQuery(QUERY_KEYS.audit.list(query), () =>
    auditApi.list({ ...toParams(query), page: query.page, limit: query.limit }),
  )

  const search = useCallback((filters: AuditFilters) => {
    setQuery((prev) => ({ ...prev, ...filters, page: 1 }))
  }, [])

  const setPage = useCallback((page: number) => setQuery((prev) => ({ ...prev, page })), [])

  const total = data?.meta?.total ?? 0

  const exportCsv = useCallback(async () => {
    // 前端先擋省一次請求；後端仍會再擋（直接打 API、查詢後資料又增加），訊息同一句
    if (total > EXPORT_MAX_ROWS) {
      message.error(`匯出筆數超過 ${EXPORT_MAX_ROWS.toLocaleString("en-US")} 筆，請縮小查詢範圍`)
      return
    }
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
      // blob 請求的錯誤 body 也是 Blob，`toApiError` 讀不到後端訊息（如 DP_AUDIT_001）
      message.error((await toBlobApiError(err)).errorMessage)
    } finally {
      setExporting(false)
    }
  }, [query, total, message])

  return {
    items: data?.data ?? [],
    total,
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
