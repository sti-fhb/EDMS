import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { REMIND_THRESHOLD_DAYS, REVIEW_STATUS_LABELS, REVIEW_TYPE_LABELS } from "./schemas"
import type { ReviewDetail, VersionMeta } from "./schemas"
import { reviewApi } from "./reviewService"
import { useCompleted, usePending, useReviewDetail } from "./useReview"
import { Pagination } from "../../components/Pagination"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { downloadVersionFile } from "../detail/detailService"

const PAGE_SIZE = 20

/** 版本下載列（版本號 / 狀態標籤 / 檔名 / 下載）。 */
function VersionRow({ docId, meta, label }: { docId: string; meta: VersionMeta; label: string }) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1, py: 0.5 }}>
      <Box>
        <Typography variant="body2">
          {meta.version_no ?? "—"} <Chip size="small" label={label} sx={{ ml: 1 }} />
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {meta.file_name ?? "（無檔案）"}
        </Typography>
      </Box>
      {meta.file_name && (
        <Button size="small" onClick={() => downloadVersionFile(docId, meta.version_id, meta.file_name ?? "file")}>
          下載
        </Button>
      )}
    </Box>
  )
}

/** 簽核明細面板（變更摘要 + 新舊版下載 + 核准 / 退回）。 */
function DetailPanel({
  detail,
  onApprove,
  onReject,
  busy,
}: {
  detail: ReviewDetail
  onApprove: () => void
  onReject: () => void
  busy: boolean
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
      <Typography variant="subtitle2" gutterBottom>
        簽核明細 — {detail.doc_name}（{REVIEW_TYPE_LABELS[detail.review_type] ?? detail.review_type}）
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        變更摘要：{detail.change_summary || "（無）"}
      </Typography>
      <Divider sx={{ my: 1 }} />
      {detail.new_version && <VersionRow docId={detail.doc_id} meta={detail.new_version} label="待審版本" />}
      {detail.current_version && <VersionRow docId={detail.doc_id} meta={detail.current_version} label="目前發布版" />}
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
        需逐段比對請下載新舊版檔案分別檢視（不提供線上預覽）。
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
        <Button variant="contained" onClick={onApprove} disabled={busy}>
          核准並發布
        </Button>
        <Button variant="outlined" color="warning" onClick={onReject} disabled={busy}>
          退回
        </Button>
      </Stack>
    </Paper>
  )
}

/**
 * 簽核中心（US6 / DM04）：審核者處理指派給自己之送審——待簽核（核准並發布 / 退回）與已完成兩頁籤。
 * 核准為原子發布（版本切換 + 通知）；退回必填原因；停留 ≥ 門檻天數之項目標紅警示。
 */
export function DmReviewPage() {
  const { message, confirm } = useNotification()
  const qc = useQueryClient()
  const [tab, setTab] = useState<"pending" | "completed">("pending")
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")
  const [rejectError, setRejectError] = useState("")
  const [page, setPage] = useState(1)

  const { data: pending, isPending: pendingLoading } = usePending()
  const { data: detail } = useReviewDetail(tab === "pending" ? selectedId : null)
  const { data: completed } = useCompleted(page, PAGE_SIZE)

  const afterAction = () => {
    setSelectedId(null)
    qc.invalidateQueries({ queryKey: ["dm-review", "pending"] })
    qc.invalidateQueries({ queryKey: ["dm-review", "completed"] })
  }

  const approveMut = useMutation({
    mutationFn: (reviewId: number) => reviewApi.approve(reviewId),
    onSuccess: () => {
      message.success("已核准並發布，已通知撰寫者") // DM-MSG-DM04-001
      afterAction()
    },
    onError: (e) => message.error(toApiError(e).errorMessage),
  })

  const rejectMut = useMutation({
    mutationFn: ({ reviewId, reason }: { reviewId: number; reason: string }) => reviewApi.reject(reviewId, reason),
    onSuccess: () => {
      message.success("已退回並通知撰寫者") // DM-MSG-DM04-005
      setRejectOpen(false)
      setRejectReason("")
      afterAction()
    },
    onError: (e) => message.error(toApiError(e).errorMessage),
  })

  const onApprove = () => {
    if (selectedId == null) return
    // 二次確認（DM-MSG-DM04-003）
    confirm({
      title: "確定核准此項目？",
      content: "核准後將立即發布並通知相關人員，此動作即時生效。",
      okText: "確認核准",
      cancelText: "取消",
      onOk: () => approveMut.mutate(selectedId),
    })
  }

  const submitReject = () => {
    if (selectedId == null) return
    if (!rejectReason.trim()) {
      setRejectError("請填寫退回原因") // DM-MSG-DM04-004
      return
    }
    rejectMut.mutate({ reviewId: selectedId, reason: rejectReason.trim() })
  }

  const busy = approveMut.isPending || rejectMut.isPending
  const pendingRows = pending ?? []
  const completedRows = completed?.data ?? []

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        簽核中心
      </Typography>

      <Tabs
        value={tab}
        onChange={(_, v) => {
          setTab(v)
          setSelectedId(null)
        }}
        sx={{ mb: 2 }}
      >
        <Tab value="pending" label={`待簽核${pending ? `（${pending.length}）` : ""}`} />
        <Tab value="completed" label={`已完成${completed ? `（${completed.meta.total}）` : ""}`} />
      </Tabs>

      {tab === "pending" ? (
        <Paper sx={{ p: 2 }}>
          {pendingLoading ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
              <CircularProgress size={28} />
            </Box>
          ) : pendingRows.length === 0 ? (
            <Alert severity="info">目前沒有待簽核項目。</Alert>
          ) : (
            <>
              <Typography variant="caption" color="text.secondary">
                點擊任一列查看簽核明細
              </Typography>
              <Table size="small" sx={{ mt: 1 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>文件名稱</TableCell>
                    <TableCell>分類</TableCell>
                    <TableCell>送審版本</TableCell>
                    <TableCell>送審者</TableCell>
                    <TableCell>送審時間</TableCell>
                    <TableCell>停留天數</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pendingRows.map((row) => {
                    const overdue = row.waiting_days >= REMIND_THRESHOLD_DAYS
                    return (
                      <TableRow
                        key={row.review_id}
                        hover
                        selected={row.review_id === selectedId}
                        sx={{ cursor: "pointer" }}
                        onClick={() => setSelectedId(row.review_id)}
                      >
                        <TableCell>
                          {row.doc_name}
                          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                            {REVIEW_TYPE_LABELS[row.review_type] ?? row.review_type}
                          </Typography>
                        </TableCell>
                        <TableCell>{row.category_code}</TableCell>
                        <TableCell>{row.version_no ?? "—"}</TableCell>
                        <TableCell>{row.submitter_name ?? row.submitter_id}</TableCell>
                        <TableCell>{row.submit_date.slice(0, 10)}</TableCell>
                        <TableCell
                          sx={{ color: overdue ? "error.main" : undefined, fontWeight: overdue ? 700 : undefined }}
                        >
                          {row.waiting_days} 天{overdue ? " ⚠" : ""}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
              {selectedId != null && detail && (
                <DetailPanel detail={detail} onApprove={onApprove} onReject={() => setRejectOpen(true)} busy={busy} />
              )}
            </>
          )}
        </Paper>
      ) : (
        <Paper sx={{ p: 2 }}>
          {completedRows.length === 0 ? (
            <Alert severity="info">尚無已完成之簽核。</Alert>
          ) : (
            <>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>文件名稱</TableCell>
                    <TableCell>類型</TableCell>
                    <TableCell>版本</TableCell>
                    <TableCell>結果</TableCell>
                    <TableCell>完成時間</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {completedRows.map((row) => (
                    <TableRow key={row.review_id}>
                      <TableCell>{row.doc_name}</TableCell>
                      <TableCell>{REVIEW_TYPE_LABELS[row.review_type] ?? row.review_type}</TableCell>
                      <TableCell>{row.version_no ?? "—"}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          color={row.status === "APPROVED" ? "success" : "warning"}
                          label={REVIEW_STATUS_LABELS[row.status] ?? row.status}
                        />
                      </TableCell>
                      <TableCell>{row.complete_date?.slice(0, 10) ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {completed && (
                <Box sx={{ mt: 2 }}>
                  <Pagination
                    page={completed.meta.page}
                    total={completed.meta.total}
                    pageSize={completed.meta.limit}
                    onPageChange={setPage}
                  />
                </Box>
              )}
            </>
          )}
        </Paper>
      )}

      {/* 退回原因 Dialog */}
      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>退回送審</DialogTitle>
        <DialogContent>
          <TextField
            label="退回原因"
            required
            fullWidth
            multiline
            minRows={3}
            autoFocus
            value={rejectReason}
            onChange={(e) => {
              setRejectReason(e.target.value)
              setRejectError("")
            }}
            error={!!rejectError}
            helperText={rejectError}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOpen(false)}>取消</Button>
          <Button variant="contained" color="warning" onClick={submitReject} disabled={rejectMut.isPending}>
            確認退回
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
