import Alert from "@mui/material/Alert"
import Chip from "@mui/material/Chip"
import Pagination from "@mui/material/Pagination"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { formatDateTime } from "../../utils/date"
import { approvalsApi } from "./approvalsService"
import type { MyApprovalRow } from "./schemas"

/**
 * 學員視角——我已通過核可的課程（`FR-ET-US17-03`）。
 *
 * 進畫面即載入，**沒有查詢框**：對象恆為自己，沒有什麼好查的。
 *
 * ⚠️ 不通過與已撤銷的紀錄**不在這裡被過濾掉，而是後端根本不回傳**。所以這支元件
 * 不需要（也不該）寫任何 `filter`——看到有人補上過濾邏輯時，要先確認是不是後端漏了。
 */
export function StudentApprovalList() {
  const [page, setPage] = useState(1)
  const { data, isPending } = usePagedQuery<MyApprovalRow>(QUERY_KEYS.etApprovals.mine(page), () =>
    approvalsApi.mine({ page }),
  )

  if (isPending) {
    return (
      <Typography variant="body2" color="text.secondary">
        載入中…
      </Typography>
    )
  }

  const rows = data?.data ?? []
  if (rows.length === 0) {
    return <Alert severity="info">您目前尚無已通過核可的課程</Alert>
  }

  const totalPages = data?.meta.total_pages ?? 0
  return (
    <Stack spacing={2}>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>課程</TableCell>
              <TableCell>核可結果</TableCell>
              <TableCell>核可時間</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.course_id}>
                <TableCell>{row.course_name}</TableCell>
                <TableCell>
                  {/* 本清單恆為已通過，故為靜態標籤而非依欄位渲染——後端不回 `result`。 */}
                  <Chip size="small" color="success" label="已通過" />
                </TableCell>
                <TableCell>{formatDateTime(row.approved_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="caption" color="text.secondary">
          您已通過核可的課程，共 {data?.meta.total ?? 0} 筆
        </Typography>
        {totalPages > 1 && <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} />}
      </Stack>
    </Stack>
  )
}
