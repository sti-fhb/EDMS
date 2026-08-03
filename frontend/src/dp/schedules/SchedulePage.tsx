import EditIcon from "@mui/icons-material/Edit"
import HistoryIcon from "@mui/icons-material/History"
import ScheduleIcon from "@mui/icons-material/Schedule"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import { useMemo } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
import { ScheduleEditDialog } from "./ScheduleEditDialog"
import { useSchedules } from "./useSchedules"
import type { ScheduleLogRow, ScheduleRow } from "./schedulesService"

/** 執行結果 badge：SUCCESS 綠 / FAILED 紅 / SKIPPED 灰。 */
function ResultChip({ status }: { status: string | null }) {
  if (!status) return <>—</>
  const color = status === "FAILED" ? "error" : status === "SUCCESS" ? "success" : "default"
  return <Chip size="small" color={color} label={status} />
}

export function SchedulePage() {
  const s = useSchedules()

  const columns = useMemo<AppColumn<ScheduleRow>[]>(
    () => [
      { key: "job_id", title: "Job", render: (_v, r) => `${r.job_id} — ${r.job_name}` },
      { key: "module", title: "所屬模組", dataIndex: "module" },
      { key: "cron_expr", title: "Cron", dataIndex: "cron_expr" },
      {
        key: "is_enabled",
        title: "狀態",
        render: (_v, r) =>
          r.is_enabled ? <Chip size="small" color="success" label="啟用" /> : <Chip size="small" label="停用" />,
      },
      { key: "last_run_date", title: "最近執行", render: (_v, r) => formatDateTime(r.last_run_date) },
      { key: "next_run_date", title: "下次執行", render: (_v, r) => formatDateTime(r.next_run_date) },
      {
        key: "actions",
        title: "操作",
        align: "right",
        render: (_v, r) => (
          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
            <IconButton size="small" aria-label="執行歷程" onClick={() => s.openLogs(r.job_id)}>
              <HistoryIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" aria-label="編輯" onClick={() => s.openEdit(r)}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Stack>
        ),
      },
    ],
    [s],
  )

  const logColumns = useMemo<AppColumn<ScheduleLogRow>[]>(
    () => [
      { key: "start_date", title: "起", render: (_v, r) => formatDateTime(r.start_date) },
      { key: "end_date", title: "訖", render: (_v, r) => formatDateTime(r.end_date) },
      { key: "status", title: "結果", render: (_v, r) => <ResultChip status={r.status} /> },
      { key: "error_msg", title: "錯誤 / 跳過原因", render: (_v, r) => r.error_msg ?? "—" },
    ],
    [],
  )

  return (
    <>
      <CrudPageLayout
        icon={<ScheduleIcon color="primary" />}
        title="排程作業總覽"
        table={
          <AppTable columns={columns} data={s.jobs} rowKey="job_id" loading={s.jobsLoading} emptyText="尚無排程作業" />
        }
      />

      {s.formVisible && s.editingRecord && (
        <ScheduleEditDialog
          key={s.editingRecord.job_id}
          job={s.editingRecord}
          saving={s.saving}
          onSave={s.handleSave}
          onCancel={s.closeForm}
        />
      )}

      <Dialog open={s.selectedJob !== null} onClose={s.closeLogs} maxWidth="md" fullWidth>
        <DialogTitle>執行歷程 {s.selectedJob}</DialogTitle>
        <DialogContent dividers>
          <AppTable
            columns={logColumns}
            data={s.logs}
            rowKey="log_id"
            loading={s.logsLoading}
            emptyText="尚無排程執行紀錄"
          />
          <Pagination page={s.page} total={s.logsTotal} pageSize={s.limit} onPageChange={s.setPage} />
        </DialogContent>
        <DialogActions>
          <Button onClick={s.closeLogs}>關閉</Button>
        </DialogActions>
      </Dialog>
    </>
  )
}