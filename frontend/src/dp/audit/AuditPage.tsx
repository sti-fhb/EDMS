import JournalIcon from "@mui/icons-material/Article"
import DownloadIcon from "@mui/icons-material/Download"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
import { AuditDetailDialog } from "./AuditDetailDialog"
import type { AuditLogRow } from "./auditService"
import { EMPTY_AUDIT_FILTERS, useAuditLogs } from "./useAuditLogs"
import type { AuditFilters } from "./useAuditLogs"

const MODULE_OPTIONS = ["全部", "DP", "ET", "DM"]
const ACTION_OPTIONS = ["全部", "LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE"]
const RESULT_OPTIONS = ["全部", "SUCCESS", "FAIL"]

/** 「全部」對應空字串（不帶入查詢）。 */
function selectValue(v: string): string {
  return v === "全部" ? "" : v
}
function displayValue(v: string): string {
  return v === "" ? "全部" : v
}

export function AuditPage() {
  const audit = useAuditLogs()
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS)

  const setField = (key: keyof AuditFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))

  const columns = useMemo<AppColumn<AuditLogRow>[]>(
    () => [
      { key: "created_date", title: "時間", render: (_v, r) => formatDateTime(r.created_date) },
      { key: "operator", title: "操作者", render: (_v, r) => r.operator_name ?? r.operator_id },
      { key: "module", title: "模組", dataIndex: "module" },
      { key: "func_name", title: "功能", dataIndex: "func_name" },
      { key: "action_type", title: "類別", render: (_v, r) => <Chip size="small" label={r.action_type} /> },
      {
        key: "result",
        title: "結果",
        render: (_v, r) => <Chip size="small" color={r.result === "FAIL" ? "error" : "success"} label={r.result} />,
      },
      { key: "target_id", title: "對象", render: (_v, r) => r.target_id ?? "—" },
      { key: "source_ip", title: "來源 IP", render: (_v, r) => r.source_ip ?? "—" },
      {
        key: "detail",
        title: "明細",
        align: "right",
        render: (_v, r) => (
          <IconButton size="small" aria-label="明細" onClick={() => audit.setSelected(r)}>
            <VisibilityIcon fontSize="small" />
          </IconButton>
        ),
      },
    ],
    [audit],
  )

  return (
    <>
      <CrudPageLayout
        icon={<JournalIcon color="primary" />}
        title="操作記錄（稽核）"
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
              sx={{ minWidth: 120 }}
            >
              {MODULE_OPTIONS.map((o) => (
                <MenuItem key={o} value={o}>
                  {o}
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
              {ACTION_OPTIONS.map((o) => (
                <MenuItem key={o} value={o}>
                  {o}
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
              {RESULT_OPTIONS.map((o) => (
                <MenuItem key={o} value={o}>
                  {o}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              type="date"
              size="small"
              label="起日"
              value={filters.date_from}
              onChange={(e) => setField("date_from", e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              type="date"
              size="small"
              label="訖日"
              value={filters.date_to}
              onChange={(e) => setField("date_to", e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <Button variant="outlined" size="small" onClick={() => audit.search(filters)}>
              查詢
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
