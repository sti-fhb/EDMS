import Paper from "@mui/material/Paper"
import type { ReactNode } from "react"

/**
 * 標題列下方的白底卡：放分頁（Tabs）或篩選列（搜尋欄、下拉）。
 * `CrudPageLayout` 的篩選區與各頁的分頁列共用它，三個模組的分頁頁面才會長得一樣
 * （白底、細框、內距與下方間距皆同）。
 */
export function FilterCard({ children }: { children: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      {children}
    </Paper>
  )
}
