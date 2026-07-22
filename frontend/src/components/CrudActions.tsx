import AddIcon from "@mui/icons-material/Add"
import RefreshIcon from "@mui/icons-material/Refresh"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"

interface CrudActionsProps {
  onRefresh: () => void
  /** 省略則不渲染新增按鈕（唯讀頁面）。 */
  onAdd?: () => void
  addLabel?: string
}

/** CRUD 頁面「重新整理 +（可選）新增」按鈕組。 */
export function CrudActions({ onRefresh, onAdd, addLabel = "建立" }: CrudActionsProps) {
  return (
    <Stack direction="row" spacing={1}>
      <Button variant="outlined" size="small" startIcon={<RefreshIcon />} onClick={onRefresh}>
        重新整理
      </Button>
      {onAdd && (
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={onAdd}>
          {addLabel}
        </Button>
      )}
    </Stack>
  )
}
