import Box from "@mui/material/Box"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import type { ReactNode } from "react"

interface CrudPageLayoutProps {
  icon?: ReactNode
  title: string
  /** 篩選列內容（搜尋欄、下拉等）。 */
  filterContent?: ReactNode
  /** 右上操作區（通常放 <CrudActions />）。 */
  actions?: ReactNode
  /** 列表區（通常放 <AppTable />）。 */
  table: ReactNode
  /** 分頁列（通常放 <Pagination />）。 */
  pagination?: ReactNode
  /** 表單區（通常放 <FormCard />，以 `visible && <Form/>` 條件渲染）。 */
  form?: ReactNode
}

/**
 * CRUD 列表頁骨架：標題列 + 篩選 / 操作 + 表格 + 分頁 + 表單 slot。
 * 統一頁面外觀，禁止各頁手拼 Box + Paper。
 *
 * 目前提供 props 版 API（涵蓋標準用法）；compound 子元件（Header/Filter…）待有客製需求時再擴充。
 */
export function CrudPageLayout({ icon, title, filterContent, actions, table, pagination, form }: CrudPageLayoutProps) {
  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          {icon}
          <Typography variant="h5" component="h1">
            {title}
          </Typography>
        </Stack>
        {actions}
      </Stack>

      {filterContent && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          {filterContent}
        </Paper>
      )}

      <Paper variant="outlined">{table}</Paper>

      {pagination}

      {form}
    </Box>
  )
}
