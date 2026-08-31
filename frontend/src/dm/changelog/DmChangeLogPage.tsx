import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
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

import { downloadChangeLogCsv } from "./changeLogService"
import { EMPTY_CHANGE_LOG_FILTERS } from "./schemas"
import type { ChangeLogFilters } from "./schemas"
import { useChangeLogSearch } from "./useChangeLog"
import { useDmAdminAccess } from "../access/useDmAdminAccess"
import { Pagination } from "../../components/Pagination"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"

const PAGE_SIZE = 20

/** 今日 yyyy-mm-dd（操作時間不會是未來，用於日期上限）。 */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * 文件變更歷程查詢（US11 / DM08，管理者）：跨文件查公開變更歷程（發布 / 廢止事件），依日期區間 /
 * 申請人or核准人（帳號或姓名）/ 操作類型**即時**搜尋；可匯出 CSV 供資安稽核。入口與後端皆限 DM_ADMIN。
 */
export function DmChangeLogPage() {
  const { message } = useNotification()
  const [filters, setFilters] = useState<ChangeLogFilters>(EMPTY_CHANGE_LOG_FILTERS)
  const [applied, setApplied] = useState<ChangeLogFilters>(EMPTY_CHANGE_LOG_FILTERS)
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)

  // 先以 admin-access 判權限：非管理者不渲染搜尋 UI、清單查詢僅在具管理者權限時才發（避免先閃搜尋列再跳無權限）。
  const { data: access, isPending: accessPending, isError: accessError } = useDmAdminAccess()
  const canAccess = access?.can_access ?? false
  const denied = accessError || access?.can_access === false
  const { data, isPending, isError } = useChangeLogSearch({ ...applied, page, limit: PAGE_SIZE }, { enabled: canAccess })

  // 即時篩選：任一條件異動即防抖套用查詢並回第一頁，無「查詢」按鈕
  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(filters)
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [filters])

  const setField = (key: keyof ChangeLogFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))

  const onExport = async () => {
    setExporting(true)
    try {
      await downloadChangeLogCsv(applied)
    } catch {
      message.error("匯出失敗，請稍後再試")
    } finally {
      setExporting(false)
    }
  }

  const rows = data?.data ?? []

  // 無權限（非管理者 / 非 DM 角色）：僅顯示標題 + 錯誤訊息，不渲染搜尋列 / 清單（DM-MSG-DM08-002）
  if (denied) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          文件變更歷程查詢
        </Typography>
        <Alert severity="error">您無權限存取此頁面</Alert>
      </Box>
    )
  }

  // 權限確認中：僅顯示標題 + spinner，不先閃搜尋列
  if (accessPending) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          文件變更歷程查詢
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
        文件變更歷程查詢
      </Typography>

      {/* 搜尋列（即時篩選，無查詢按鈕）*/}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr 2fr 1fr" }, gap: 1.5 }}>
          <TextField
            size="small"
            type="date"
            label="日期 起"
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: filters.dateTo || today() } }}
            value={filters.dateFrom}
            onChange={(e) => setField("dateFrom", e.target.value)}
          />
          <TextField
            size="small"
            type="date"
            label="日期 迄"
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: filters.dateFrom || undefined, max: today() } }}
            value={filters.dateTo}
            onChange={(e) => setField("dateTo", e.target.value)}
          />
          <TextField
            size="small"
            label="申請人 / 核准人（帳號或姓名）"
            value={filters.keyword}
            onChange={(e) => setField("keyword", e.target.value)}
          />
          <TextField
            size="small"
            select
            label="操作類型"
            value={filters.operation}
            onChange={(e) => setField("operation", e.target.value)}
          >
            <MenuItem value="">全部</MenuItem>
            <MenuItem value="PUBLISH">發布</MenuItem>
            <MenuItem value="OBSOLETE">廢止</MenuItem>
          </TextField>
        </Box>
      </Paper>

      {/* 結果 */}
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="subtitle2">變更紀錄{data ? `（共 ${data.meta.total} 筆）` : ""}</Typography>
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
          <Alert severity="info">查無符合條件之變更紀錄。</Alert>
        ) : (
          <>
            <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "14%" }}>時間</TableCell>
                  <TableCell sx={{ width: "11%" }}>申請人</TableCell>
                  <TableCell sx={{ width: "11%" }}>核准人</TableCell>
                  <TableCell sx={{ width: "8%" }}>操作</TableCell>
                  <TableCell sx={{ width: "22%" }}>文件</TableCell>
                  <TableCell sx={{ width: "10%" }}>版本</TableCell>
                  <TableCell sx={{ width: "24%" }}>備註</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.change_log_id}>
                    <TableCell>{formatDateTime(row.operation_time)}</TableCell>
                    <TableCell>{row.applicant_name ?? row.applicant_id}</TableCell>
                    <TableCell>{row.approver_name ?? row.approver_id}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={row.operation === "PUBLISH" ? "success" : "error"}
                        label={row.operation === "PUBLISH" ? "發布" : "廢止"}
                      />
                    </TableCell>
                    <TableCell>
                      {row.doc_name}
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                        {row.doc_id}
                      </Typography>
                    </TableCell>
                    <TableCell>{row.version_no ?? "—"}</TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {row.note ?? "—"}
                      </Typography>
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
