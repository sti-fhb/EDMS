import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import FormControlLabel from "@mui/material/FormControlLabel"
import Stack from "@mui/material/Stack"
import Switch from "@mui/material/Switch"
import TextField from "@mui/material/TextField"
import { useState } from "react"

import type { ScheduleRow, ScheduleUpdatePayload } from "./schedulesService"

/** 編輯排程：JOB_ID 唯讀；JOB_NAME / CRON_EXPR / 啟停 可改。cron 變更即時生效。
 *  由 SchedulePage 以 `key={job.job_id}` 重掛，故 useState 每次以該列值初始化。 */
export function ScheduleEditDialog({
  job,
  saving,
  onSave,
  onCancel,
}: {
  job: ScheduleRow
  saving: boolean
  onSave: (jobId: string, payload: ScheduleUpdatePayload) => void
  onCancel: () => void
}) {
  const [jobName, setJobName] = useState(job.job_name)
  const [cronExpr, setCronExpr] = useState(job.cron_expr)
  const [isEnabled, setIsEnabled] = useState(job.is_enabled)

  const submit = () => onSave(job.job_id, { job_name: jobName, cron_expr: cronExpr, is_enabled: isEnabled })

  return (
    <Dialog open onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>編輯排程</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField label="Job ID" value={job.job_id} size="small" disabled fullWidth />
          <TextField
            label="作業名稱"
            value={jobName}
            onChange={(e) => setJobName(e.target.value)}
            size="small"
            fullWidth
            required
          />
          <TextField
            label="Cron 表達式"
            value={cronExpr}
            onChange={(e) => setCronExpr(e.target.value)}
            size="small"
            fullWidth
            required
            helperText="例：0 8 * * *（每日 08:00 UTC）。變更即時生效。"
          />
          <FormControlLabel
            control={<Switch checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />}
            label="啟用"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>取消</Button>
        <Button variant="contained" onClick={submit} disabled={saving || !jobName.trim() || !cronExpr.trim()}>
          儲存
        </Button>
      </DialogActions>
    </Dialog>
  )
}