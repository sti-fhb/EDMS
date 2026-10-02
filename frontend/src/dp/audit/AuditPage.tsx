import ClearIcon from "@mui/icons-material/FilterAltOff"
import DownloadIcon from "@mui/icons-material/Download"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useEffect, useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
import { AuditDetailDialog } from "./AuditDetailDialog"
import { labelOf } from "./auditLabels"
import type { AuditLogRow, AuditOption } from "./auditService"
import { EMPTY_AUDIT_FILTERS, useAuditLogs, useAuditOptions } from "./useAuditLogs"
import type { AuditFilters } from "./useAuditLogs"

const ALL = "全部"

/** 在後端選項前面補一個「全部」sentinel（空值不顯示 label，故不用空字串當 value）。 */
function withAll(options: AuditOption[]): AuditOption[] {
  return [{ value: ALL, label: ALL }, ...options]
}

/** 「全部」對應空字串（不帶入查詢）。 */
function selectValue(v: string): string {
  return v === ALL ? "" : v
}
function displayValue(v: string): string {
  return v === "" ? ALL : v
}

/** 操作者顯示：姓名 → email →（皆無，如 SYSTEM）原 ID。 */
function operatorText(r: AuditLogRow): string {
  return r.operator_name ?? r.operator_email ?? r.operator_id
}

/** 今日（yyyy-mm-dd），供日期上限。 */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function AuditPage() {
  const audit = useAuditLogs()
  const { setSelected, search } = audit
  const { funcOptions, actionOptions, resultOptions, moduleOptions } = useAuditOptions()
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS)

  const setField = (key: keyof AuditFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))
  const clearFilters = () => setFilters(EMPTY_AUDIT_FILTERS)

  // 即時篩選：篩選欄異動即（防抖）套用查詢，無「查詢」按鈕
  useEffect(() => {
    const timer = setTimeout(() => search(filters), 400)
    return () => clearTimeout(timer)
  }, [filters, search])

  const columns = useMemo<AppColumn<AuditLogRow>[]>(
    () => [
      { key: "created_date", title: "時間", render: (_v, r) => formatDateTime(r.created_date) },
      { key: "operator", title: "操作者", render: (_v, r) => operatorText(r) },
      { key: "func_label", title: "功能", dataIndex: "func_label" },
      {
        key: "action_type",
        title: "類別",
        render: (_v, r) => <Chip size="small" label={labelOf(actionOptions, r.action_type)} />,
      },
      {
        key: "result",
        title: "結果",
        // 配色仍依原英文碼判定，label 才轉中文
        render: (_v, r) => (
          <Chip
            size="small"
            color={r.result === "FAIL" ? "error" : "success"}
            label={labelOf(resultOptions, r.result)}
          />
        ),
      },
      { key: "target", title: "對象", render: (_v, r) => r.target_display ?? "—" },
      { key: "source_ip", title: "來源 IP", render: (_v, r) => r.source_ip ?? "—" },
      {
        key: "detail",
        title: "明細",
        align: "right",
        render: (_v, r) => (
          <IconButton size="small" aria-label="明細" onClick={() => setSelected(r)}>
            <VisibilityIcon fontSize="small" />
          </IconButton>
        ),
      },
    ],
    [setSelected, actionOptions, resultOptions],
  )

  return (
    <>
      <CrudPageLayout
        code="DP05"
        filterContent={
          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={2}
            alignItems={{ md: "flex-end" }}
            flexWrap="wrap"
            useFlexGap
          >
            <TextField
              size="small"
              label="操作者（姓名 / Email）"
              value={filters.operator}
              onChange={(e) => setField("operator", e.target.value)}
              sx={{ minWidth: 200 }}
            />
            <TextField
              select
              size="small"
              label="模組"
              value={displayValue(filters.module)}
              onChange={(e) => setField("module", selectValue(e.target.value))}
              sx={{ minWidth: 130 }}
            >
              {withAll(moduleOptions).map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="功能"
              value={displayValue(filters.func)}
              onChange={(e) => setField("func", selectValue(e.target.value))}
              sx={{ minWidth: 190 }}
            >
              {withAll(funcOptions).map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="操作類別"
              value={displayValue(filters.action_type)}
              onChange={(e) => setField("action_type", selectValue(e.target.value))}
              sx={{ minWidth: 130 }}
            >
              {withAll(actionOptions).map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="執行結果"
              value={displayValue(filters.result)}
              onChange={(e) => setField("result", selectValue(e.target.value))}
              sx={{ minWidth: 120 }}
            >
              {withAll(resultOptions).map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              type="date"
              size="small"
              label="起日"
              value={filters.date_from}
              onChange={(e) => setField("date_from", e.target.value)}
              slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: filters.date_to || today() } }}
            />
            <TextField
              type="date"
              size="small"
              label="訖日"
              value={filters.date_to}
              onChange={(e) => setField("date_to", e.target.value)}
              slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: filters.date_from || undefined, max: today() } }}
            />
            <Button variant="outlined" size="small" startIcon={<ClearIcon />} onClick={clearFilters}>
              清除篩選
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<DownloadIcon />}
              onClick={audit.exportCsv}
              disabled={audit.exporting}
            >
              匯出
            </Button>
          </Stack>
        }
        table={
          <AppTable
            columns={columns}
            data={audit.items}
            rowKey="log_id"
            loading={audit.loading}
            emptyText="查無符合條件之紀錄"
          />
        }
        pagination={
          <Pagination page={audit.page} total={audit.total} pageSize={audit.limit} onPageChange={audit.setPage} />
        }
      />
      <AuditDetailDialog log={audit.selected} onClose={() => audit.setSelected(null)} />
    </>
  )
}
