import DownloadIcon from "@mui/icons-material/Download"
import PersonRemoveIcon from "@mui/icons-material/PersonRemove"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
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

import { studentsApi } from "./studentsService"
import type { ApprovalResult, ApprovalStatus, CompletionStatus, StudentRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { BlockHeading } from "./BlockHeading"

const PAGE_SIZE = 20

const STATUS_LABEL: Record<CompletionStatus, { text: string; color: "default" | "warning" | "success" }> = {
  NOT_STARTED: { text: "未開始", color: "default" },
  IN_PROGRESS: { text: "進行中", color: "warning" },
  COMPLETED: { text: "已完成", color: "success" },
}

/**
 * 核可狀態的呈現（US16）。
 *
 * ⚠️ `NOT_ELIGIBLE` **不是 Chip**——它是「這一欄對他不適用」，不是一種狀態。做成 Chip
 * 會讓未完課的人在視覺上與已通過 / 未通過同級，而教師掃這一欄時要找的正是「誰可以動」。
 */
const APPROVAL_LABEL: Record<Exclude<ApprovalStatus, "NOT_ELIGIBLE">, { text: string; color: "warning" | "success" | "error" }> = {
  PENDING: { text: "待核可", color: "warning" },
  PASSED: { text: "已通過", color: "success" },
  FAILED: { text: "未通過", color: "error" },
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
  onExport,
  onApprove,
}: {
  courseId: number
  /** 課程視同關閉時為 `true`——**只停寫入**，清單與匯出照常（AC 10）。 */
  readOnly: boolean
  onRemove: (student: StudentRow) => void
  onExport: () => void
  /**
   * 核可 / 撤銷（US16）。`students` 長度為 1 即單筆，`result` 為 `null` 代表撤銷。
   *
   * 單筆與批次走同一個回呼——`StudentsPage` 才能用同一段確認框邏輯處理兩者。
   */
  onApprove: (students: StudentRow[], result: ApprovalResult | null) => void
}) {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const params = { page, limit: PAGE_SIZE }
  const { data, isPending, isError } = usePagedQuery(QUERY_KEYS.etStudents.list(courseId, params), () =>
    studentsApi.listStudents(courseId, params),
  )

  const rows = data?.data ?? []
  const totalPages = data?.meta.total_pages ?? 0

  // 🔴 課程是否啟用線下核可，由**列上是否帶回核可狀態**判定，不另外打一支
  // `GET /courses/{id}`。後端契約是「`REQUIRE_APPROVAL = false` 時五個核可欄位全為
  // null」，同一門課的每一列一致。
  //
  // ⚠️ 判定寫成 `typeof === "string"` 而非 `!== null`：**後者連 `undefined` 也算成
  // 「有」**。欄位缺席（舊版後端、或 fixture 漏給）時會靜默把整個核可欄打開，而那一欄
  // 的每一格都是空的、按鈕也點不動——看起來像壞掉，而不是像「這門課不做線下核可」。
  //
  // 零筆時整個區塊顯示「此課程尚無學員加入」，沒有核可對象，工具列不出現也是對的。
  const approvalEnabled = rows.some((r) => typeof r.approval_status === "string")

  // 可勾選的只有「待核可」——未完課（NOT_ELIGIBLE）沒有資格，已通過 / 未通過要改判得先
  // 撤銷並填原因（wireframe 對已有結果者只給「撤銷」）。後端對這兩類一律跳過，逐列的
  // `canApprove` 讓教師在按下去之前就看得出來。
  const selectedRows = rows.filter((r) => selected.has(r.user_id))

  const toggle = (userId: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) next.delete(userId)
      else next.add(userId)
      return next
    })

  // 🔴 **換頁必須清空勾選。⛔ 不要因為全選鈕拿掉了就一併移除這段。**
  //
  // `selected` 是純 id 的 Set，而真正送出的名單是 `rows.filter(...)`——只認**本頁**的
  // 列。不清的話：第 1 頁勾 3 人 → 翻到第 2 頁，`selected.size` 仍是 3（工具列維持
  // 啟用），但 `selectedRows` 是空的 → 送出空 `user_ids` → 後端 422，教師看到一個對
  // 不上任何操作的錯誤。**這條與全選無關，逐一勾選同樣會踩到。**
  //
  // > 2026-09-23（#415）依裁示移除表頭全選鈕，改由教師逐一勾選。原本另有一種只有全選
  // > 才踩得到的狀況（在第 2 頁按全選會用新 Set 整個覆蓋 `selected`，第 1 頁那幾人被
  // > 無聲清掉而請求照樣成功、只是少了人），隨該鈕一併消失。
  const goToPage = (next: number) => {
    setPage(next)
    setSelected(new Set())
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <BlockHeading title="已加入學員" note="本課程已加入之學員清單、完課狀態與進度" />
        {/* 匯出是**讀**，課程關閉時照常可用（AC 10 明訂含匯出 CSV）。
            走 blob 而非 href——token 是 memory-only Bearer，原生導覽不帶 header */}
        <Button size="small" startIcon={<DownloadIcon />} onClick={() => onExport()}>
          匯出 CSV
        </Button>
      </Stack>

      {approvalEnabled && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          action={
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant="contained"
                disabled={readOnly || selectedRows.length === 0}
                onClick={() => onApprove(selectedRows, "PASS")}
              >
                批次核可通過
              </Button>
              <Button
                size="small"
                color="error"
                disabled={readOnly || selectedRows.length === 0}
                onClick={() => onApprove(selectedRows, "FAIL")}
              >
                批次不通過
              </Button>
            </Stack>
          }
        >
          本課程<strong>需線下核可</strong>（實機 / 口頭考核）：勾選<strong>待核可</strong>學員可批次核可。
        </Alert>
      )}

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
                  {/* 空的表頭格——逐列仍有勾選框，少一格會讓整排欄位錯位。
                      全選鈕已於 #415 依裁示移除，改由教師逐一勾選。 */}
                  {approvalEnabled && <TableCell padding="checkbox" />}
                  <TableCell>學員</TableCell>
                  <TableCell>加入日期</TableCell>
                  <TableCell>完課狀態</TableCell>
                  <TableCell sx={{ minWidth: 140 }}>學習進度</TableCell>
                  <TableCell align="right">平均成績</TableCell>
                  {approvalEnabled && <TableCell>核可狀態</TableCell>}
                  <TableCell>最後活動</TableCell>
                  {/* 「核可」與「操作」分欄（#415）：核可是對學習結果的裁示，移除是對
                      名單的管理。混在一欄時「移除」緊鄰「不通過」，而兩者的後果差距極大
                      ——一個是判定未通過，一個是把人踢出課程。 */}
                  {approvalEnabled && <TableCell align="center">核可</TableCell>}
                  <TableCell align="center">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const status = STATUS_LABEL[row.completion_status]
                  const canApprove = row.approval_status === "PENDING"
                  const hasResult = row.approval_status === "PASSED" || row.approval_status === "FAILED"
                  return (
                    <TableRow key={row.user_id} hover>
                      {approvalEnabled && (
                        <TableCell padding="checkbox">
                          <Tooltip title={canApprove ? "" : "未完課或已有核可紀錄，不可批次核可"}>
                            {/* span 包住：disabled 的元件不觸發事件，Tooltip 會失效 */}
                            <span>
                              <Checkbox
                                size="small"
                                inputProps={{ "aria-label": `選取 ${row.user_name ?? row.user_id}` }}
                                checked={selected.has(row.user_id)}
                                disabled={readOnly || !canApprove}
                                onChange={() => toggle(row.user_id)}
                              />
                            </span>
                          </Tooltip>
                        </TableCell>
                      )}
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
                      {approvalEnabled && (
                        <TableCell>
                          {row.approval_status === "NOT_ELIGIBLE" ? (
                            /* 純文字、不用 Chip——這是「不適用」，不是一種狀態 */
                            <Typography variant="caption" color="text.secondary">
                              未達核可資格
                            </Typography>
                          ) : row.approval_status !== null ? (
                            <Stack spacing={0.25}>
                              <Chip
                                size="small"
                                color={APPROVAL_LABEL[row.approval_status].color}
                                label={APPROVAL_LABEL[row.approval_status].text}
                                sx={{ alignSelf: "flex-start" }}
                              />
                              {row.approved_by_name !== null && (
                                <Typography variant="caption" color="text.secondary">
                                  {row.approved_by_name} 核可 {formatDateTime(row.approved_at)}
                                </Typography>
                              )}
                              {row.approval_note !== null && (
                                <Typography variant="caption" color="text.secondary">
                                  {row.approval_note}
                                </Typography>
                              )}
                            </Stack>
                          ) : null}
                        </TableCell>
                      )}
                      <TableCell>{formatDateTime(row.last_activity_at)}</TableCell>
                      {approvalEnabled && (
                        <TableCell align="center">
                          <Stack direction="row" spacing={0.5} justifyContent="center">
                            {/* 三顆核可鈕依狀態互斥（wireframe 行 1345~1372）：
                                待核可 → 通過 + 不通過；已有結果 → 只有撤銷（不給直接改判，
                                改判須先撤銷並填原因）；未達核可資格 → 兩者皆無。 */}
                            {canApprove && (
                              <>
                                <Button size="small" disabled={readOnly} onClick={() => onApprove([row], "PASS")}>
                                  通過
                                </Button>
                                <Button
                                  size="small"
                                  color="error"
                                  disabled={readOnly}
                                  onClick={() => onApprove([row], "FAIL")}
                                >
                                  不通過
                                </Button>
                              </>
                            )}
                            {hasResult && (
                              <Button
                                size="small"
                                color="secondary"
                                disabled={readOnly}
                                onClick={() => onApprove([row], null)}
                              >
                                撤銷
                              </Button>
                            )}
                          </Stack>
                        </TableCell>
                      )}
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
              <Pagination count={totalPages} page={page} onChange={(_, p) => goToPage(p)} />
            </Stack>
          )}
        </>
      )}
    </Paper>
  )
}
