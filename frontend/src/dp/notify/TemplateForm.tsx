import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { TemplateContentSchema } from "./schemas"
import type { Template } from "./templatesService"
import { FormCard } from "../../components/FormCard"
import { getFieldErrors } from "../../utils/zodUtils"

interface TemplateFormProps {
  editingRecord: Template
  saving: boolean
  onSave: (content: { subject: string; body: string }) => void
  onCancel: () => void
}

/**
 * 通知範本內容編輯表單（US9）：主旨 + 內文（信件完整內容）。
 * 管道 / 啟停於清單行內操作，故不在此表單；儲存採 VERSION 樂觀鎖（由 hook 帶入現值版本）。
 */
export function TemplateForm({ editingRecord, saving, onSave, onCancel }: TemplateFormProps) {
  const [subject, setSubject] = useState(editingRecord.subject)
  const [body, setBody] = useState(editingRecord.body)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const handleSave = () => {
    const parsed = TemplateContentSchema.safeParse({ subject, body })
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (parsed.success) onSave(parsed.data)
  }

  return (
    <FormCard
      title={`編輯範本 — ${editingRecord.template_code} ${editingRecord.template_name}`}
      onSave={handleSave}
      onCancel={onCancel}
      saving={saving}
      saveLabel="儲存"
    >
      <Stack spacing={2}>
        <TextField
          label="主旨"
          size="small"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          error={Boolean(fieldErrors.subject)}
          helperText={fieldErrors.subject}
          fullWidth
        />
        <TextField
          label="內文"
          size="small"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          error={Boolean(fieldErrors.body)}
          helperText={fieldErrors.body}
          fullWidth
          multiline
          minRows={6}
        />
        {editingRecord.variables && (
          <Typography variant="caption" color="text.secondary">
            可用變數：{editingRecord.variables}
          </Typography>
        )}
      </Stack>
    </FormCard>
  )
}
