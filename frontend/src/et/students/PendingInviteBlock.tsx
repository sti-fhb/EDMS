import RefreshIcon from "@mui/icons-material/Refresh"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
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
import Tooltip from "@mui/material/Tooltip"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { studentsApi } from "./studentsService"
import type { PendingInviteRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"

const PAGE_SIZE = 20

/** `2026-04-15 09:00`。 */
function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * ET03「待加入」分頁（ET-12 / #342 / US12）。
 *
 * 列出已寄出 Email 邀請但尚未加入的學員，可再次寄送或撤回。
 *
 * ## 🔴 兩個動作的關閉行為**相反**，這不是筆誤
 *
 * | 動作 | 課程關閉時 | 理由 |
 * |---|---|---|
 * | 再次寄送 | **禁用**（`FR-ET-US12-06`）| 課都關了不該再招生 |
 * | 撤回 | **仍可執行**（SA 裁示 2026-09-16）| 止血動作。教師發現邀請寄錯人時，若撤回被擋，那條錯誤連結會一直有效到再開課、且再開課當下立刻可用 |
 *
 * 後端 `revoke()` 也刻意不掛關閉守門，兩側一致。**不要為了「一致性」把撤回也禁用。**
 *
 * ## 「全部再次寄送」不做
 *
 * Wireframe（`index.html:1683`）有那顆按鈕，但 spec 的 6 條 FR、7 條場景、5 條訊息與
 * 規劃文件的 6 條 AC 全都沒有 → SA 裁示視為未採納之草案（2026-09-16）。
 */
export function PendingInviteBlock({
  courseId,
  readOnly,
  onResend,
  onRevoke,
}: {
  courseId: number
  /** 課程視同關閉——**只停「再次寄送」**，清單與撤回照常。 */
  readOnly: boolean
  onResend: (invite: PendingInviteRow) => void
  onRevoke: (invite: PendingInviteRow) => void
}) {
  const [page, setPage] = useState(1)
  const params = { page, limit: PAGE_SIZE }
  const { data, isPending, isError } = usePagedQuery(QUERY_KEYS.etStudents.pendingInvites(courseId, params), () =>
    studentsApi.listPendingInvites(courseId, params),
  )

  const rows = data?.data ?? []
  const totalPages = data?.meta.total_pages ?? 0

  if (isError) return <Alert severity="error">待加入清單載入失敗，請重新整理。</Alert>
  if (isPending) return <Typography variant="body2">載入中…</Typography>

  if (rows.length === 0) {
    return <Alert severity="info">目前沒有待加入的邀請。</Alert>
  }

  return (
    <Stack spacing={2}>
      {readOnly && (
        // ET-MSG-ET03-105。常駐而非 tooltip：ET-16 排程執行前，期間已過的課程狀態欄
        // 仍寫著「已發布」，不解釋的話教師會以為系統壞了。
        <Alert severity="warning">
          課程關閉中，暫無法<strong>再次寄送</strong>（再開課後恢復）。
          <strong>撤回邀請不受影響</strong>——寄錯對象時仍可立即失效。
        </Alert>
      )}

      <Alert severity="info">以下學員已收到邀請信但尚未點擊連結加入課程。</Alert>

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>收件 Email</TableCell>
              <TableCell>最後寄送</TableCell>
              <TableCell>邀請狀態</TableCell>
              <TableCell align="center">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.invitation_id} hover>
                <TableCell>{row.email}</TableCell>
                <TableCell>{formatDateTime(row.last_sent_at)}</TableCell>
                <TableCell>
                  <Chip size="small" label="待加入" />
                </TableCell>
                <TableCell align="center">
                  <Stack direction="row" spacing={1} justifyContent="center">
                    <Tooltip title={readOnly ? "課程關閉中，無法再次寄送" : "重寄後原連結將失效"}>
                      {/* span 包住：disabled 的按鈕不觸發事件，Tooltip 會失效 */}
                      <span>
                        <Button
                          size="small"
                          startIcon={<RefreshIcon />}
                          disabled={readOnly}
                          onClick={() => onResend(row)}
                        >
                          再次寄送
                        </Button>
                      </span>
                    </Tooltip>
                    {/* 撤回**不**受 readOnly 影響——見本檔頂部說明，不要順手加上去 */}
                    <Button size="small" color="error" onClick={() => onRevoke(row)}>
                      撤回
                    </Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {totalPages > 1 && (
        <Stack direction="row" justifyContent="flex-end">
          <Pagination size="small" count={totalPages} page={page} onChange={(_, p) => setPage(p)} />
        </Stack>
      )}
    </Stack>
  )
}
