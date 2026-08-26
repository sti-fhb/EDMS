import DownloadIcon from "@mui/icons-material/Download"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
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
import CloseIcon from "@mui/icons-material/Close"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"

import { REMIND_THRESHOLD_DAYS, RejectReqSchema, REVIEW_TYPE_LABELS, reviewStatusLabel } from "./schemas"
import type { ReviewDetail, VersionMeta } from "./schemas"
import { downloadObsoleteFile, downloadReviewFile, reviewApi } from "./reviewService"
import { useCompleted, usePending, useReviewDetail } from "./useReview"
import { Pagination } from "../../components/Pagination"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError, toBlobApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"

const PAGE_SIZE = 20

/** 版本對照列（版本 / 狀態 / 檔案 / 下載）。 */
function VersionCompareRow({
  meta,
  statusLabel,
  statusColor,
  highlight,
  onDownload,
}: {
  meta: VersionMeta
  statusLabel: string
  statusColor: "success" | "warning"
  highlight?: boolean
  onDownload: (versionId: number, filename: string) => void
}) {
  return (
    <TableRow sx={highlight ? { bgcolor: "action.hover" } : undefined}>
      <TableCell sx={{ fontWeight: 600 }}>{meta.version_no ?? "—"}</TableCell>
      <TableCell>
        <Chip size="small" color={statusColor} label={statusLabel} />
      </TableCell>
      <TableCell>{meta.file_name ?? "（無檔案）"}</TableCell>
      <TableCell align="right">
        {meta.file_name && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={() => onDownload(meta.version_id, meta.file_name ?? "file")}
          >
            下載
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}

/** 簽核明細面板（wireframe：標題 + 類型 badge + 右上角關閉 + 版本對照表 + 核准 / 退回）。 */
function DetailPanel({
  detail,
  onApprove,
  onReject,
  onClose,
  onDownload,
  onDownloadObsoleteFile,
  busy,
}: {
  detail: ReviewDetail
  onApprove: () => void
  onReject: () => void
  onClose: () => void
  onDownload: (versionId: number, filename: string) => void
  onDownloadObsoleteFile: () => void
  busy: boolean
}) {
  const isNewVersion = detail.review_type === "NEW_VERSION"
  const isObsolete = detail.review_type === "OBSOLETE"
  return (
    <Paper
      variant="outlined"
      sx={{ p: 2, mt: 2, borderLeft: 4, borderLeftColor: isObsolete ? "error.main" : "success.main" }}
    >
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          簽核明細 — {detail.doc_name}
          <Chip
            size="small"
            color={isObsolete ? "error" : "primary"}
            label={REVIEW_TYPE_LABELS[detail.review_type] ?? detail.review_type}
            sx={{ ml: 1 }}
          />
        </Typography>
        <IconButton size="small" onClick={onClose} aria-label="收合" title="收合">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* 摘要（三類送審一致用「變更摘要」標題；廢止類內容為申請人填寫之廢止原因） */}
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
        變更摘要{" "}
        <Typography component="span" variant="caption" color="text.secondary">
          （{isObsolete ? "申請人填寫" : "撰寫者填寫"}）
        </Typography>
      </Typography>
      <Box sx={{ bgcolor: "grey.100", px: 2, py: 1, mb: 2, borderRadius: 1 }}>
        <Typography variant="body2">
          {(isObsolete ? detail.obsolete_reason : detail.change_summary) || "（無）"}
        </Typography>
      </Box>

      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        {isObsolete ? "廢止檔案" : isNewVersion ? "版本對照" : "新增檔案"}
      </Typography>
      <Table size="small" sx={{ mb: 1 }}>
        <TableHead>
          <TableRow>
            <TableCell>{isObsolete ? "目前發布版" : isNewVersion ? "版本" : "首版版本"}</TableCell>
            <TableCell>狀態</TableCell>
            <TableCell>檔案</TableCell>
            <TableCell align="right">動作</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {detail.current_version && (
            <VersionCompareRow
              meta={detail.current_version}
              statusLabel="目前發布版"
              statusColor="success"
              onDownload={onDownload}
            />
          )}
          {detail.new_version && (
            <VersionCompareRow
              meta={detail.new_version}
              statusLabel={isObsolete ? "廢止待簽核" : isNewVersion ? "待審新版" : "待審首版"}
              statusColor="warning"
              highlight
              onDownload={onDownload}
            />
          )}
        </TableBody>
      </Table>

      {isObsolete && detail.obsolete_file_name && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
            廢止附件
          </Typography>
          <Button size="small" variant="outlined" startIcon={<DownloadIcon />} onClick={onDownloadObsoleteFile}>
            下載廢止附件
          </Button>
        </Box>
      )}

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
        {isObsolete
          ? "核准後整份文件廢止並自文件庫下架；歷史版本永久保留供稽核。廢止原因與附件寫入紀錄。"
          : isNewVersion
            ? "需要逐段比對請下載新舊版檔案分別檢視（不提供線上預覽）。"
            : "本文件為首次提交，無舊版可比對；請依首版摘要與檔案內容判斷是否核准發布。"}
      </Typography>

      <Stack direction="row" spacing={1}>
        <Button variant="contained" color={isObsolete ? "error" : "primary"} onClick={onApprove} disabled={busy}>
          {isObsolete ? "核准並廢止" : "核准並發布"}
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
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<"pending" | "completed">("pending")
  // 由個人專區「前往簽核中心」深連結（?reviewId=）帶入 → 掛載時預選該筆，於待簽核頁自動展開明細
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const rid = searchParams.get("reviewId")
    const n = Number(rid)
    return rid != null && !Number.isNaN(n) ? n : null
  })
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")
  const [rejectError, setRejectError] = useState("")
  const [page, setPage] = useState(1)
  const [completedKeyword, setCompletedKeyword] = useState("")

  const { data: pending, isPending: pendingLoading } = usePending()
  const { data: detail } = useReviewDetail(tab === "pending" ? selectedId : null)
  const { data: completed } = useCompleted(page, PAGE_SIZE, completedKeyword)

  const afterAction = () => {
    setSelectedId(null)
    qc.invalidateQueries({ queryKey: ["dm-review", "pending"] })
    qc.invalidateQueries({ queryKey: ["dm-review", "completed"] })
  }

  const approveMut = useMutation({
    mutationFn: ({ reviewId }: { reviewId: number; isObsolete: boolean }) => reviewApi.approve(reviewId),
    onSuccess: (_data, vars) => {
      // 廢止核准 → 文件下架；一般 → 發布（DM-MSG-DM04-001）
      message.success(vars.isObsolete ? "已核准廢止，文件已下架並通知撰寫者" : "已核准並發布，已通知撰寫者")
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
    const isObsolete = detail?.review_type === "OBSOLETE"
    // 二次確認（DM-MSG-DM04-003）
    confirm({
      title: isObsolete ? "確定核准廢止此文件？" : "確定核准此項目？",
      content: isObsolete
        ? "核准後文件將立即廢止並自文件庫下架、通知撰寫者，此動作即時生效。"
        : "核准後將立即發布並通知相關人員，此動作即時生效。",
      okText: isObsolete ? "確認廢止" : "確認核准",
      cancelText: "取消",
      onOk: () => approveMut.mutate({ reviewId: selectedId, isObsolete }),
    })
  }

  const handleDownload = async (versionId: number, filename: string) => {
    if (selectedId == null) return
    try {
      await downloadReviewFile(selectedId, versionId, filename)
    } catch (e) {
      // 檔案下載為 blob 請求，錯誤 body 亦為 blob → 以 toBlobApiError 解出真因（如查無檔案），非籠統連線異常
      message.error((await toBlobApiError(e)).errorMessage)
    }
  }

  const handleDownloadObsoleteFile = async () => {
    if (selectedId == null || !detail?.obsolete_file_name) return
    try {
      await downloadObsoleteFile(selectedId, detail.obsolete_file_name)
    } catch (e) {
      message.error((await toBlobApiError(e)).errorMessage)
    }
  }

  const submitReject = () => {
    if (selectedId == null) return
    const result = RejectReqSchema.safeParse({ reason: rejectReason }) // DM-MSG-DM04-004
    const errs = getFieldErrors(result.success ? null : result.error)
    setRejectError(errs.reason ?? "")
    if (!result.success) return
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
                <DetailPanel
                  detail={detail}
                  onApprove={onApprove}
                  onReject={() => setRejectOpen(true)}
                  onClose={() => setSelectedId(null)}
                  onDownload={handleDownload}
                  onDownloadObsoleteFile={handleDownloadObsoleteFile}
                  busy={busy}
                />
              )}
            </>
          )}
        </Paper>
      ) : (
        <Paper sx={{ p: 2 }}>
          <TextField
            size="small"
            label="搜尋文件名稱"
            value={completedKeyword}
            onChange={(e) => {
              setCompletedKeyword(e.target.value)
              setPage(1)
            }}
            sx={{ mb: 2, width: { xs: "100%", sm: 320 } }}
          />
          {completedRows.length === 0 ? (
            <Alert severity="info">{completedKeyword ? "查無符合搜尋之項目。" : "尚無已完成之簽核。"}</Alert>
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
                          label={reviewStatusLabel(row.status)}
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
