import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import type { FormEvent, ReactNode } from "react"

interface FormCardProps {
  title: string
  children: ReactNode
  onSave: () => void
  onCancel: () => void
  saving?: boolean
  saveLabel?: string
  cancelLabel?: string
}

/**
 * CRUD 表單卡片殼：標題 + 內容 slot + 儲存 / 取消。
 * 以 `<form onSubmit>` 包裹，支援 Enter 送出；儲存期間停用按鈕。
 */
export function FormCard({
  title,
  children,
  onSave,
  onCancel,
  saving = false,
  saveLabel = "儲存",
  cancelLabel = "取消",
}: FormCardProps) {
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    onSave()
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mt: 2 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        {title}
      </Typography>
      <Box component="form" onSubmit={handleSubmit} noValidate>
        {children}
        <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 3 }}>
          <Button onClick={onCancel} disabled={saving}>
            {cancelLabel}
          </Button>
          <Button type="submit" variant="contained" disabled={saving}>
            {saveLabel}
          </Button>
        </Stack>
      </Box>
    </Paper>
  )
}
