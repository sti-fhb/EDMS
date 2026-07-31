import HistoryIcon from "@mui/icons-material/History"
import ScheduleIcon from "@mui/icons-material/Schedule"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import { useMemo } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
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
      { key: "job_id", title: "Job", render: (_v, r) => `${r.job_id}　${r.job_name}` },
      { key: "module", title: "所屬模組", dataIndex: "module" },
      { key: "cron_expr", title: "Cron", dataIndex: "cron_expr" },
      {
        key: "is_enabled",
        title: "啟停",
        render: (_v, r) =>
          r.is_enabled ? <Chip size="small" color="success" label="啟用" /> : <Chip size="small" label="停用" />,
      },
      { key: "last_run_date", title: "最近執行", render: (_v, r) => formatDateTime(r.last_run_date) },
      { key: "last_run_status", title: "結果", render: (_v, r) => <ResultChip status={r.last_run_status} /> },
      {
        key: "logs",
        title: "歷程",
        align: "right",
        render: (_v, r) => (
          <IconButton size="small" aria-label="執行歷程" onClick={() => s.openLogs(r.job_id)}>
            <HistoryIcon fontSize="small" />
          </IconButton>
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

      <Dialog open={s.selectedJob !== null} onClose={s.closeLogs} maxWidth="md" fullWidth>
        <DialogTitle>執行歷程　{s.selectedJob}</DialogTitle>
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
