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
          {loading ? (
            <TableRow>
              <TableCell colSpan={columns.length} align="center" sx={{ py: 4 }}>
                <CircularProgress size={28} />
              </TableCell>
            </TableRow>
          ) : data.length === 0 ? (
            <TableRow>
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
