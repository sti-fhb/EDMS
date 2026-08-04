import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableRow from "@mui/material/TableRow"
import Typography from "@mui/material/Typography"

import { formatDateTime } from "../../utils/date"
import { actionLabel, resultLabel } from "./auditLabels"
import type { AuditLogRow } from "./auditService"

/** JSON 字串格式化呈現；parse 失敗則原樣顯示（none → 「—」）。 */
function formatJson(value: string | null): string {
  if (!value) return "—"
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

const PRE_SX = {
  m: 0,
  p: 1,
  bgcolor: "action.hover",
  borderRadius: 1,
  fontSize: "0.8rem",
  fontFamily: "monospace",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
} as const

/** 操作記錄明細（唯讀 modal）：完整欄位 + 執行結果 / 事件描述 + 異動前後值。 */
export function AuditDetailDialog({ log, onClose }: { log: AuditLogRow | null; onClose: () => void }) {
  return (
    <Dialog open={log !== null} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>操作記錄明細</DialogTitle>
      <DialogContent dividers>
        {log && (
          <>
            <Table size="small">
              <TableBody>
                <TableRow>
                  <TableCell sx={{ width: 130, fontWeight: 600 }}>時間</TableCell>
                  <TableCell>{formatDateTime(log.created_date)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>操作者</TableCell>
                  <TableCell>{log.operator_name ?? log.operator_email ?? log.operator_id}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>功能</TableCell>
                  <TableCell>{log.func_label}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>操作類別</TableCell>
                  <TableCell>
                    <Chip size="small" label={actionLabel(log.action_type)} />
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>執行結果</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      color={log.result === "FAIL" ? "error" : "success"}
                      label={resultLabel(log.result)}
                    />
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>對象</TableCell>
                  <TableCell>{log.target_display ?? "—"}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>來源 IP</TableCell>
                  <TableCell>{log.source_ip ?? "—"}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>事件描述</TableCell>
                  <TableCell>{log.description ?? "—"}</TableCell>
                </TableRow>
              </TableBody>
            </Table>

            <Typography variant="body2" sx={{ mt: 2, mb: 0.5, fontWeight: 600 }}>
              異動前值
            </Typography>
            <Box component="pre" sx={PRE_SX}>
              {formatJson(log.before_value)}
            </Box>

            <Typography variant="body2" sx={{ mt: 2, mb: 0.5, fontWeight: 600 }}>
              異動後值
            </Typography>
            <Box component="pre" sx={PRE_SX}>
              {formatJson(log.after_value)}
            </Box>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>關閉</Button>
      </DialogActions>
    </Dialog>
  )
}