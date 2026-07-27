import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useRef } from "react"
import type { FormEvent, ReactNode } from "react"

interface FormCardProps {
  title: string
  children: ReactNode
  onSave: () => void
  onCancel: () => void
  saving?: boolean
  saveLabel?: string
  cancelLabel?: string
  /** 最大寬度，預設 600（對齊 sti-ui-design §5 / 主專案 TBMS FormCard）。 */
  maxWidth?: number | string
}

/**
 * CRUD 表單卡片殼：標題 + 內容 slot + 儲存 / 取消。
 *
 * 以卡片形式展開（**非 Modal**，對齊 sti-ui-design §5 與主專案 TBMS FormCard）：
 * 綠色 2px 實線邊框、max-width 600、展開時平滑捲動至此。
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
  maxWidth = 600,
}: FormCardProps) {
  const ref = useRef<HTMLDivElement>(null)

  // 表單展開時平滑捲動至此（列表長時避免使用者漏看下方展開的表單）；jsdom 無此 API 故以 ?. 保護
  useEffect(() => {
    ref.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })
  }, [])

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    onSave()
  }

  return (
    <Paper
      ref={ref}
      variant="outlined"
      sx={{ p: 3, mt: 2, maxWidth, border: 2, borderColor: "primary.main" }}
    >
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