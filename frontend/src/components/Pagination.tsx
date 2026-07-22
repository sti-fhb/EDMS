import Box from "@mui/material/Box"
import MenuItem from "@mui/material/MenuItem"
import MuiPagination from "@mui/material/Pagination"
import TextField from "@mui/material/TextField"

interface PaginationProps {
  page: number
  total: number
  onPageChange: (page: number) => void
  pageSize?: number
  onPageSizeChange?: (pageSize: number) => void
  pageSizeOptions?: number[]
}

const DEFAULT_PAGE_SIZE = 10
const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50]

/**
 * 後端分頁控制列。`total === 0` 時自動隱藏；切換每頁筆數時自動回第 1 頁。
 */
export function Pagination({
  page,
  total,
  onPageChange,
  pageSize = DEFAULT_PAGE_SIZE,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
}: PaginationProps) {
  if (total === 0) return null

  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  return (
    <Box sx={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 2, mt: 2 }}>
      {onPageSizeChange && (
        <TextField
          select
          size="small"
          label="每頁筆數"
          value={pageSize}
          onChange={(e) => {
            onPageSizeChange(Number(e.target.value))
            onPageChange(1)
          }}
          sx={{ width: 120 }}
        >
          {pageSizeOptions.map((opt) => (
            <MenuItem key={opt} value={opt}>
              {opt}
            </MenuItem>
          ))}
        </TextField>
      )}
      <MuiPagination
        page={page}
        count={pageCount}
        onChange={(_e, value) => onPageChange(value)}
        color="primary"
        shape="rounded"
      />
    </Box>
  )
}
