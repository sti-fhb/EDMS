import FormControlLabel from "@mui/material/FormControlLabel"
import Stack from "@mui/material/Stack"
import Switch from "@mui/material/Switch"
import TextField from "@mui/material/TextField"
import { useState } from "react"

import { ScheduleUpdateSchema } from "./schemas"
import type { ScheduleRow, ScheduleUpdatePayload } from "./schedulesService"
import { FormCard } from "../../components/FormCard"
import { getFieldErrors } from "../../utils/zodUtils"

/** 編輯排程：JOB_ID 唯讀；JOB_NAME / CRON_EXPR / 啟停 可改。cron 變更即時生效。
 *  表格下方展開之卡片（非 Modal，對齊其他維護頁）；由 SchedulePage 以 `key={job.job_id}`
 *  重掛，故 useState 每次以該列值初始化。 */
export function ScheduleForm({
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const handleSave = () => {
    const parsed = ScheduleUpdateSchema.safeParse({
      job_name: jobName,
      cron_expr: cronExpr,
      is_enabled: isEnabled,
    })
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (parsed.success) onSave(job.job_id, parsed.data)
  }

  return (
    <FormCard title={`編輯排程 — ${job.job_id}`} onSave={handleSave} onCancel={onCancel} saving={saving}>
      <Stack spacing={2}>
        <TextField label="Job ID" value={job.job_id} size="small" disabled fullWidth />
        <TextField
          label="作業名稱"
          value={jobName}
          onChange={(e) => setJobName(e.target.value)}
          size="small"
          fullWidth
          error={Boolean(fieldErrors.job_name)}
          helperText={fieldErrors.job_name}
        />
        <TextField
          label="Cron 表達式"
          value={cronExpr}
          onChange={(e) => setCronExpr(e.target.value)}
          size="small"
          fullWidth
          error={Boolean(fieldErrors.cron_expr)}
          helperText={fieldErrors.cron_expr ?? "例：0 8 * * *（每日 08:00 UTC）。變更即時生效。"}
        />
        <FormControlLabel
          control={<Switch checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />}
          label="啟用"
        />
      </Stack>
    </FormCard>
  )
}
