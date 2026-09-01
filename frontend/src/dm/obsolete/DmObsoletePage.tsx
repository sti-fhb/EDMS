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
import { useNavigate } from "react-router-dom"

import { downloadObsoleteCsv } from "./obsoleteService"
import { EMPTY_OBSOLETE_FILTERS } from "./schemas"
import type { ObsoleteFilters } from "./schemas"
import { useObsoleteSearch } from "./useObsolete"
import { useDmAdminAccess } from "../access/useDmAdminAccess"
import { Pagination } from "../../components/Pagination"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"
import { DM_CATEGORIES } from "../library/schemas"

const PAGE_SIZE = 20

/** 今日 yyyy-mm-dd（廢止日期上限；廢止時間不會是未來）。 */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * 已廢止文件查詢（US10 / DM06，管理者）：以關鍵字（文件名 / 廢止原因）/ 分類 / 廢止日期區間**即時**
 * 搜尋已廢止文件 → 點列進 US4 read-only 詳細頁；可匯出 CSV 供稽核封存。入口與後端皆限 DM_ADMIN。
 * 原作者欄採末版〔在架版〕作者（SA 裁示 Q2=B）。
 */
export function DmObsoletePage() {
  const navigate = useNavigate()
  const { message } = useNotification()
  const [filters, setFilters] = useState<ObsoleteFilters>(EMPTY_OBSOLETE_FILTERS)
  const [applied, setApplied] = useState<ObsoleteFilters>(EMPTY_OBSOLETE_FILTERS)
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)

  // 先以 access 端點判權限：非管理者不渲染搜尋 UI、清單查詢僅在具管理者權限時才發（避免先閃搜尋列再跳無權限）。
  const { data: access, isPending: accessPending, isError: accessError } = useDmAdminAccess()
  const canAccess = access?.can_access ?? false
  const denied = accessError || access?.can_access === false
  const { data, isPending, isError } = useObsoleteSearch(
    { ...applied, page, limit: PAGE_SIZE },
    { enabled: canAccess },
  )

  // 即時篩選：任一條件異動即防抖套用查詢並回第一頁，無「搜尋」按鈕
  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(filters)
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [filters])

  const setField = (key: keyof ObsoleteFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))

  const onExport = async () => {
    setExporting(true)
    try {
      await downloadObsoleteCsv(applied)
    } catch {
      message.error("匯出失敗，請稍後再試")
    } finally {
      setExporting(false)
    }
  }

  const rows = data?.data ?? []

  // 無權限（非管理者 / 非 DM 角色）：僅顯示標題 + 錯誤訊息，不渲染搜尋列 / 清單（DM-MSG-DM06-002）
  if (denied) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          已廢止文件查詢
        </Typography>
        <Alert severity="error">您無權限存取此頁面</Alert>
      </Box>
    )
  }

  // 權限確認中：僅顯示標題 + spinner，不先閃搜尋列（避免非管理者看到搜尋 UI 後才跳無權限）
  if (accessPending) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          已廢止文件查詢
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
        已廢止文件查詢
      </Typography>

      {/* 搜尋列（即時篩選，無搜尋按鈕）*/}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr 1fr 1fr" }, gap: 1.5 }}>
          <TextField
            size="small"
            label="關鍵字（文件名 / 廢止原因）"
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
          <TextField
            size="small"
            type="date"
            label="廢止日期 起"
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: filters.dateTo || today() } }}
            value={filters.dateFrom}
            onChange={(e) => setField("dateFrom", e.target.value)}
          />
          <TextField
            size="small"
            type="date"
            label="廢止日期 迄"
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: filters.dateFrom || undefined, max: today() } }}
            value={filters.dateTo}
            onChange={(e) => setField("dateTo", e.target.value)}
          />
        </Box>
      </Paper>

      {/* 結果 */}
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="subtitle2">已廢止文件{data ? `（共 ${data.meta.total} 筆）` : ""}</Typography>
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
          <Alert severity="info">查無符合條件之已廢止文件。</Alert>
        ) : (
          <>
            <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "24%" }}>文件名稱</TableCell>
                  <TableCell sx={{ width: "10%" }}>分類</TableCell>
                  <TableCell sx={{ width: "10%" }}>原作者</TableCell>
                  <TableCell sx={{ width: "14%" }}>廢止時間</TableCell>
                  <TableCell sx={{ width: "10%" }}>廢止申請人</TableCell>
                  <TableCell sx={{ width: "10%" }}>核准者</TableCell>
                  <TableCell sx={{ width: "22%" }}>廢止原因</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.doc_id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(`/dm/documents/${row.doc_id}`)}
                  >
                    <TableCell>
                      {row.doc_name}
                      {row.latest_version_no && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                          版本 {row.latest_version_no}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip size="small" label={row.category_name} />
                    </TableCell>
                    <TableCell>{row.author_name ?? row.author_id ?? "—"}</TableCell>
                    <TableCell>{formatDateTime(row.obsolete_date)}</TableCell>
                    <TableCell>{row.applicant_name ?? row.applicant_id ?? "—"}</TableCell>
                    <TableCell>{row.approver_name ?? row.approver_id ?? "—"}</TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {row.obsolete_reason ?? "—"}
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
