import Box from "@mui/material/Box"
import CircularProgress from "@mui/material/CircularProgress"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import type { ReactNode } from "react"

/** 表格欄位定義。`dataIndex` 直取欄位值；`render` 自訂渲染（優先於 dataIndex）。 */
export interface AppColumn<T> {
  key: string
  title: string
  dataIndex?: keyof T
  align?: "left" | "right" | "center"
  width?: number | string
  render?: (value: unknown, row: T) => ReactNode
}

interface AppTableProps<T> {
  columns: AppColumn<T>[]
  data: T[]
  /** 列的唯一鍵：欄位名或自訂函式。 */
  rowKey: keyof T | ((row: T) => string)
  loading?: boolean
  emptyText?: string
}

function resolveRowKey<T>(row: T, rowKey: keyof T | ((row: T) => string)): string {
  return typeof rowKey === "function" ? rowKey(row) : String(row[rowKey])
}

/**
 * loading / 空資料列：退回 theme 的全域列 hover（#832），它們不是一列資料。
 *
 * 能用單一個 `&` 蓋過去，是因為 theme 那條**刻意保持在最低 specificity**
 * （`.MuiTableRow-root:hover`，見 `muiTheme.ts` 的說明）。⛔ 若日後有人把 theme 的
 * 選擇器寫複雜（例如加 `:not(...)`），這裡會**靜默失效**——畫面上看不出是被誰蓋住。
 */
const PLACEHOLDER_ROW = { "&:hover": { backgroundColor: "transparent" } } as const

/**
 * CRUD 列表通用表格。統一 loading（置中轉圈）與空資料呈現，禁止各頁手拼 MUI Table。
 */
export function AppTable<T>({ columns, data, rowKey, loading = false, emptyText = "查無資料" }: AppTableProps<T>) {
  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            {columns.map((col) => (
              <TableCell key={col.key} align={col.align} sx={{ fontWeight: 600, width: col.width }}>
                {col.title}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {/* `PLACEHOLDER_ROW`：loading / 空資料不是「一列資料」，不該有 hover 高亮。
              #832 把 hover 設到 theme 的 `MuiTableRow` 之後，這兩列會跟著亮——那是
              新行為（原本只有資料列帶 `hover` prop），故在此退回。 */}
          {loading ? (
            <TableRow sx={PLACEHOLDER_ROW}>
              <TableCell colSpan={columns.length} align="center" sx={{ py: 4 }}>
                <CircularProgress size={28} />
              </TableCell>
            </TableRow>
          ) : data.length === 0 ? (
            <TableRow sx={PLACEHOLDER_ROW}>
              <TableCell colSpan={columns.length} align="center" sx={{ py: 4 }}>
                <Box component="span" sx={{ color: "text.secondary" }}>
                  {emptyText}
                </Box>
              </TableCell>
            </TableRow>
          ) : (
            data.map((row) => (
              <TableRow key={resolveRowKey(row, rowKey)} hover>
                {columns.map((col) => (
                  <TableCell key={col.key} align={col.align}>
                    {col.render
                      ? col.render(col.dataIndex ? row[col.dataIndex] : undefined, row)
                      : col.dataIndex
                        ? String(row[col.dataIndex] ?? "")
                        : null}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
