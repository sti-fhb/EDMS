import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import LinearProgress from "@mui/material/LinearProgress"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useEffect, useState } from "react"

import { downloadKpiCsv } from "./kpiService"
import { EMPTY_KPI_FILTERS } from "./schemas"
import type { KpiFilters } from "./schemas"
import { useKpiSearch } from "./useKpi"
import { useDmAdminAccess } from "../access/useDmAdminAccess"
import { DM_CATEGORIES } from "../library/schemas"
import { Pagination } from "../../components/Pagination"
import { useNotification } from "../../contexts/NotificationContext"

const PAGE_SIZE = 20
const TITLE = "閱讀統計 KPI"

/** 閱讀率顯示（0~1 → 百分比字串；null＝應看=0）。 */
function ratePct(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`
}

/**
 * 閱讀統計 KPI（US13 / DM10，管理者）：逐文件應看/已看/未看/閱讀率，依關鍵字（文件名）/ 分類**即時**
 * 查詢；頂部統計卡（整體平均閱讀率 / 閱讀率<50% 文件數）；可匯出 CSV。入口與後端皆限 DM_ADMIN。
 */
export function DmKpiPage() {
  const { message } = useNotification()
  const [filters, setFilters] = useState<KpiFilters>(EMPTY_KPI_FILTERS)
  const [applied, setApplied] = useState<KpiFilters>(EMPTY_KPI_FILTERS)
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)

  // 先以 admin-access 判權限：非管理者不渲染查詢 UI、清單查詢僅在具管理者權限時才發（避免先閃搜尋列再跳無權限）。
  const { data: access, isPending: accessPending, isError: accessError } = useDmAdminAccess()
  const canAccess = access?.can_access ?? false
  const denied = accessError || access?.can_access === false
  const { data, isPending, isError } = useKpiSearch({ ...applied, page, limit: PAGE_SIZE }, { enabled: canAccess })

  // 即時篩選：任一條件異動即防抖套用查詢並回第一頁，無「查詢」按鈕
  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(filters)
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [filters])

  const setField = (key: keyof KpiFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))

  const onExport = async () => {
    setExporting(true)
    try {
      await downloadKpiCsv(applied)
    } catch {
      message.error("匯出失敗，請稍後再試")
    } finally {
      setExporting(false)
    }
  }

  const rows = data?.data ?? []
  const summary = data?.summary

  // 無權限（非管理者 / 非 DM 角色）：僅顯示標題 + 錯誤訊息，不渲染查詢 UI（DM-MSG-DM10-002）
  if (denied) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          {TITLE}
        </Typography>
        <Alert severity="error">您無權限存取此頁面</Alert>
      </Box>
    )
  }

  // 權限確認中：僅顯示標題 + spinner，不先閃查詢 UI
  if (accessPending) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          {TITLE}
        </Typography>
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {TITLE}
      </Typography>

      {/* 統計卡 */}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2, mb: 2 }}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="caption" color="text.secondary">
            整體平均閱讀率
          </Typography>
          <Typography variant="h4">{summary ? ratePct(summary.overall_rate) : "—"}</Typography>
        </Paper>
        <Paper sx={{ p: 2 }}>
          <Typography variant="caption" color="text.secondary">
            閱讀率低於 50% 之文件數
          </Typography>
          <Box sx={{ display: "flex", alignItems: "baseline", gap: 1 }}>
            <Typography variant="h4">{summary?.below_50_count ?? 0}</Typography>
            <Typography variant="body2" color="text.secondary">
              ／ 共 {summary?.total_docs ?? 0} 份文件
            </Typography>
          </Box>
        </Paper>
      </Box>

      {/* 搜尋列（即時篩選，無查詢按鈕）*/}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" }, gap: 1.5 }}>
          <TextField
            size="small"
            label="關鍵字（文件名）"
            value={filters.keyword}
            onChange={(e) => setField("keyword", e.target.value)}
          />
          <TextField
            size="small"
            select
            label="分類"
            value={filters.category}
            onChange={(e) => setField("category", e.target.value)}
          >
            <MenuItem value="">全部</MenuItem>
            {DM_CATEGORIES.map((c) => (
              <MenuItem key={c.code} value={c.code}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
        </Box>
      </Paper>

      {/* 結果 */}
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="subtitle2">文件統計{data ? `（共 ${data.meta.total} 筆）` : ""}</Typography>
          <Button
            size="small"
            variant="outlined"
            disabled={exporting || (data?.meta.total ?? 0) === 0}
            onClick={onExport}
          >
            匯出 CSV
          </Button>
        </Box>

        {isPending ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : isError ? (
          <Alert severity="error">載入失敗，請稍後再試。</Alert>
        ) : rows.length === 0 ? (
          <Alert severity="info">查無符合條件之文件統計</Alert>
        ) : (
          <>
            <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "30%" }}>文件</TableCell>
                  <TableCell sx={{ width: "12%" }}>分類</TableCell>
                  <TableCell sx={{ width: "10%" }}>目前版本</TableCell>
                  <TableCell sx={{ width: "8%" }} align="right">
                    應看
                  </TableCell>
                  <TableCell sx={{ width: "8%" }} align="right">
                    已看
                  </TableCell>
                  <TableCell sx={{ width: "8%" }} align="right">
                    未看
                  </TableCell>
                  <TableCell sx={{ width: "24%" }}>閱讀率</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.doc_id}>
                    <TableCell>
                      {row.doc_name}
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                        {row.doc_id}
                      </Typography>
                    </TableCell>
                    <TableCell>{row.category_name ?? row.category_code}</TableCell>
                    <TableCell>{row.current_version_no ?? "—"}</TableCell>
                    <TableCell align="right">{row.should_see}</TableCell>
                    <TableCell align="right">{row.seen}</TableCell>
                    <TableCell align="right">{row.unseen}</TableCell>
                    <TableCell>
                      {row.rate === null ? (
                        <Typography variant="body2" color="text.secondary">
                          —（無對應閱覽者）
                        </Typography>
                      ) : (
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                          <LinearProgress
                            variant="determinate"
                            value={row.rate * 100}
                            sx={{ flexGrow: 1, height: 8, borderRadius: 1 }}
                          />
                          <Typography variant="caption" sx={{ minWidth: 44, textAlign: "right" }}>
                            {ratePct(row.rate)}
                          </Typography>
                        </Box>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data && (
              <Box sx={{ mt: 2 }}>
                <Pagination
                  page={data.meta.page}
                  total={data.meta.total}
                  pageSize={data.meta.limit}
                  onPageChange={setPage}
                />
              </Box>
            )}
          </>
        )}
      </Paper>
    </Box>
  )
}
