import DownloadIcon from "@mui/icons-material/Download"
import PersonRemoveIcon from "@mui/icons-material/PersonRemove"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import LinearProgress from "@mui/material/LinearProgress"
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

import { studentsApi, studentsCsvPaths } from "./studentsService"
import type { CompletionStatus, StudentRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { BlockHeading } from "./BlockHeading"

const PAGE_SIZE = 20

const STATUS_LABEL: Record<CompletionStatus, { text: string; color: "default" | "warning" | "success" }> = {
  NOT_STARTED: { text: "未開始", color: "default" },
  IN_PROGRESS: { text: "進行中", color: "warning" },
  COMPLETED: { text: "已完成", color: "success" },
}

/** `2026-04-15 09:00`；`null` 回破折號（與 CSV 一致）。 */
function formatDateTime(iso: string | null): string {
  if (iso === null) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * ET03 區塊 1：已加入學員清單（`FR-ET-US9-02`）。
 *
 * ## 這個表格的列**不可點**
 *
 * 區塊 1 沒有展開語意——作答明細一律在區塊 2（規格明訂操作欄不另設入口）。讓列可點會
 * 讓教師以為點下去看得到成績。
 *
 * ## 平均成績顯示「—」而非 0
 *
 * `avg_score` 為 `null` 代表**完全未作答**。0 分與未作答意義相反，混為一談會讓教師誤判
 * 需要輔導的對象。
 */
export function StudentListBlock({
  courseId,
  readOnly,
  onRemove,
}: {
  courseId: number
  /** 課程視同關閉時為 `true`——**只停寫入**，清單與匯出照常（AC 10）。 */
  readOnly: boolean
  onRemove: (student: StudentRow) => void
}) {
  const [page, setPage] = useState(1)
  const params = { page, limit: PAGE_SIZE }
  const { data, isPending, isError } = usePagedQuery(QUERY_KEYS.etStudents.list(courseId, params), () =>
    studentsApi.listStudents(courseId, params),
  )

  const rows = data?.data ?? []
  const totalPages = data?.meta.total_pages ?? 0

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <BlockHeading index={1} title="已加入學員" note="本課程已加入之學員清單、完課狀態與進度" />
        {/* 匯出是**讀**，課程關閉時照常可用（AC 10 明訂含匯出 CSV）*/}
        <Button
          size="small"
          startIcon={<DownloadIcon />}
          href={studentsCsvPaths.students(courseId)}
          target="_blank"
          rel="noopener"
        >
          匯出 CSV
        </Button>
      </Stack>

      {isError && <Typography color="error">學員清單載入失敗</Typography>}
      {isPending && <LinearProgress />}

      {!isPending && !isError && rows.length === 0 && (
        <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          此課程尚無學員加入
        </Typography>
      )}

      {rows.length > 0 && (
        <>
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>學員</TableCell>
                  <TableCell>加入日期</TableCell>
                  <TableCell>完課狀態</TableCell>
                  <TableCell sx={{ minWidth: 140 }}>學習進度</TableCell>
                  <TableCell align="right">平均成績</TableCell>
                  <TableCell>最後活動</TableCell>
                  <TableCell align="center">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const status = STATUS_LABEL[row.completion_status]
                  return (
                    <TableRow key={row.user_id} hover>
                      <TableCell>{row.user_name ?? "—"}</TableCell>
                      <TableCell>{formatDateTime(row.joined_at)}</TableCell>
                      <TableCell>
                        <Chip size="small" color={status.color} label={status.text} />
                      </TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <LinearProgress
                            variant="determinate"
                            value={row.progress_pct}
                            sx={{ flexGrow: 1, minWidth: 60 }}
                          />
                          <Typography variant="caption">{row.progress_pct}%</Typography>
                        </Stack>
                      </TableCell>
                      {/* null ＝ 完全未作答；顯示「—」不可顯示 0 */}
                      <TableCell align="right">{row.avg_score ?? "—"}</TableCell>
                      <TableCell>{formatDateTime(row.last_activity_at)}</TableCell>
                      <TableCell align="center">
                        <Tooltip title={readOnly ? "課程已關閉，無法移除學員" : "移除學員"}>
                          {/* span 包住：disabled 的按鈕不觸發事件，Tooltip 會失效 */}
                          <span>
                            <Button
                              size="small"
                              color="error"
                              startIcon={<PersonRemoveIcon />}
                              disabled={readOnly}
                              onClick={() => onRemove(row)}
                            >
                              移除
                            </Button>
                          </span>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
          {totalPages > 1 && (
            <Stack alignItems="center" sx={{ mt: 2 }}>
              <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} />
            </Stack>
          )}
        </>
      )}
    </Paper>
  )
}
