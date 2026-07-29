import LockIcon from "@mui/icons-material/Lock"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Chip from "@mui/material/Chip"
import FormControlLabel from "@mui/material/FormControlLabel"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import Switch from "@mui/material/Switch"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { TemplateUpdateSchema } from "./schemas"
import type { Channel, Template, TemplateUpdatePayload } from "./templatesService"
import { getFieldErrors } from "../../utils/zodUtils"

const CHANNELS: { value: Channel; label: string }[] = [
  { value: "EMAIL", label: "Email" },
  { value: "MSG", label: "站內" },
  { value: "BOTH", label: "兩者" },
]

/**
 * 單一通知範本編輯卡（US9）。主旨 / 內文 / 管道 / 啟停可編；變數說明唯讀顯示。
 * 系統信（is_system）之「啟用」開關禁用（不可停用，僅可編主旨內文）。
 * 由 TemplatesPage 以 `${module}.${code}.${version}` 為 key，版本變動（含衝突重載）即重置本卡狀態。
 */
export function TemplateCard({
  template,
  onSave,
}: {
  template: Template
  onSave: (module: string, code: string, payload: TemplateUpdatePayload) => Promise<boolean>
}) {
  const [subject, setSubject] = useState(template.subject)
  const [body, setBody] = useState(template.body)
  const [channel, setChannel] = useState<Channel>(template.channel)
  const [isEnabled, setIsEnabled] = useState(template.is_enabled)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    const payload = { subject, body, channel, is_enabled: isEnabled, version: template.version }
    const parsed = TemplateUpdateSchema.safeParse(payload)
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return
    setSaving(true)
    try {
      await onSave(template.module, template.template_code, parsed.data)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <Chip label={template.module} size="small" color="primary" variant="outlined" />
          <Typography variant="subtitle2" sx={{ fontFamily: "monospace" }}>
            {template.template_code}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {template.template_name}
          </Typography>
          {template.is_system && <Chip icon={<LockIcon />} label="系統信" size="small" color="default" />}
        </Stack>

        <Stack spacing={2}>
          <TextField
            label="主旨"
            size="small"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            error={"subject" in fieldErrors}
            helperText={fieldErrors.subject}
            fullWidth
          />
          <TextField
            label="內文"
            size="small"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            error={"body" in fieldErrors}
            helperText={fieldErrors.body}
            fullWidth
            multiline
            minRows={3}
          />
          {template.variables && (
            <Typography variant="caption" color="text.secondary">
              可用變數：{template.variables}
            </Typography>
          )}
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
            <TextField
              label="管道"
              size="small"
              select
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel)}
              sx={{ minWidth: 140 }}
            >
              {CHANNELS.map((c) => (
                <MenuItem key={c.value} value={c.value}>
                  {c.label}
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={isEnabled}
                  onChange={(e) => setIsEnabled(e.target.checked)}
                  disabled={template.is_system}
                />
              }
              label={template.is_system ? "啟用（系統信不可停用）" : "啟用"}
            />
            <Box sx={{ flexGrow: 1 }} />
            <Button variant="contained" onClick={handleSave} disabled={saving}>
              儲存
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            管道之「站內」訊息由各模組自理；此欄僅作為是否寄 Email 之開關依據。
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}