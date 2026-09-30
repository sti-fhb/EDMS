import Box from "@mui/material/Box"
import Paper from "@mui/material/Paper"
import type { ReactNode } from "react"

import { ScreenHeader } from "./ScreenHeader"

interface CrudPageLayoutProps {
  /** 畫面代號（如 `DP05`）：標題列 icon 與名稱取自 `navItems`，與側欄同源。 */
  code: string
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
export function CrudPageLayout({ code, filterContent, actions, table, pagination, form }: CrudPageLayoutProps) {
  // 不另加 padding：AppShell 的 main 已有 p: 3，再包一層會讓標題比其他模組頁面低一截
  return (
    <Box>
      <ScreenHeader code={code} actions={actions} />

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
