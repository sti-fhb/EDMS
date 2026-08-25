import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import Typography from "@mui/material/Typography"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import type { ActivityItem, DraftItem } from "./schemas"
import { DRAFT_KIND_LABELS, authorEventLabel, reviewerEventLabel } from "./schemas"
import { personalApi } from "./personalService"
import { useActivity, useDrafts } from "./usePersonal"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"
import { toApiError } from "../../services/http"

/**
 * 個人專區（US9 / DM07）：我的文件動態 + 草稿匣（編輯者 / 審核者）。
 * 撤回送審（撰寫者對送審中項目）→ 狀態回復 + 站內訊息（呈現於原審核者之動態）；草稿續編進 US5、刪除須確認。
 * 個人資料維護（姓名 / Email / 密碼）為另一入口，由平台 DP 提供（右上使用者選單），不在此頁。
 */
export function DmPersonalPage() {
  const [tab, setTab] = useState<"activity" | "drafts">("activity")
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        個人專區
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="activity" label="我的文件動態" />
        <Tab value="drafts" label="草稿匣" />
      </Tabs>
      {tab === "activity" ? <ActivityTab /> : <DraftsTab />}
    </Box>
  )
}

// ── 我的文件動態 ──────────────────────────────────────

function ActivityTab() {
  const { message } = useNotification()
  const qc = useQueryClient()
  const { data, isPending, isError } = useActivity()

  const withdrawMut = useMutation({
    mutationFn: (reviewId: number) => personalApi.withdraw(reviewId),
    onSuccess: () => {
      message.success("已撤回送審，已通知原指派審核者") // DM-MSG-DM07-005
      qc.invalidateQueries({ queryKey: ["dm-personal"] })
    },
    onError: (e) => message.error(toApiError(e).errorMessage),
  })

  if (isPending) return <Loading />
  if (isError || !data) return <Alert severity="error">載入動態失敗，請稍後再試。</Alert>

  const hasAuthor = data.author.length > 0
  const hasReviewer = data.reviewer.length > 0
  if (!hasAuthor && !hasReviewer) return <Alert severity="info">近 30 天無文件動態。</Alert>

  return (
    <Stack spacing={2}>
      {hasAuthor && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
            撰寫者視角（近 30 天）
          </Typography>
          <Stack divider={<Divider />} spacing={1}>
            {data.author.map((a) => (
              <AuthorRow key={a.review_id} item={a} onWithdraw={withdrawMut.mutate} busy={withdrawMut.isPending} />
            ))}
          </Stack>
        </Paper>
      )}
      {hasReviewer && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
            審核者視角（近 30 天）
          </Typography>
          <Stack divider={<Divider />} spacing={1}>
            {data.reviewer.map((a) => (
              <Box key={a.review_id} sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Chip size="small" label={reviewerEventLabel(a.status)} />
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {a.doc_name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {formatDateTime(a.submit_date)}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  )
}

function AuthorRow({
  item,
  onWithdraw,
  busy,
}: {
  item: ActivityItem
  onWithdraw: (reviewId: number) => void
  busy: boolean
}) {
  const { confirm } = useNotification()
  const withdrawable = item.status === "PENDING" // 送審中 / 廢止待簽核可撤回
  const onClick = () =>
    confirm({
      title: "確定撤回送審？",
      content: "撤回後送審項目將回到草稿 / 已發布狀態，並通知原指派審核者。",
      okText: "確認撤回",
      onOk: () => onWithdraw(item.review_id),
    })
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <Chip size="small" color={withdrawable ? "warning" : "default"} label={authorEventLabel(item.review_type, item.status)} />
      <Typography variant="body2" sx={{ flex: 1 }}>
        {item.doc_name}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {formatDateTime(item.submit_date)}
      </Typography>
      {withdrawable && (
        <Button size="small" variant="outlined" color="error" onClick={onClick} disabled={busy}>
          撤回送審
        </Button>
      )}
    </Box>
  )
}

// ── 草稿匣 ────────────────────────────────────────────

function DraftsTab() {
  const { message, confirm } = useNotification()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data, isPending, isError } = useDrafts()

  const deleteMut = useMutation({
    mutationFn: (versionId: number) => personalApi.deleteDraft(versionId),
    onSuccess: () => {
      message.success("草稿已刪除")
      qc.invalidateQueries({ queryKey: ["dm-personal", "drafts"] })
    },
    onError: (e) => message.error(toApiError(e).errorMessage),
  })

  if (isPending) return <Loading />
  if (isError || !data) return <Alert severity="error">載入草稿失敗，請稍後再試。</Alert>
  if (data.length === 0) return <Alert severity="info">目前沒有草稿。</Alert>

  const onDelete = (d: DraftItem) =>
    confirm({
      title: "確定刪除此草稿？刪除後不可復原", // DM-MSG-DM07-004
      content: "僅刪除此草稿版本，不影響已發布版本。",
      okText: "確認刪除",
      onOk: () => deleteMut.mutate(d.version_id),
    })

  return (
    <Paper sx={{ p: 2 }}>
      <Stack divider={<Divider />} spacing={1}>
        {data.map((d) => (
          <Box key={d.version_id} sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Chip size="small" label={DRAFT_KIND_LABELS[d.kind]} />
            <Box sx={{ flex: 1 }}>
              <Typography variant="body2">{d.doc_name}</Typography>
              <Typography variant="caption" color="text.secondary">
                {d.version_no ?? "（未填版號）"} ｜ {formatDateTime(d.updated_date)}
              </Typography>
            </Box>
            <Button size="small" variant="outlined" onClick={() => navigate(`/dm/documents/${d.doc_id}/edit`)}>
              繼續編輯
            </Button>
            <Button size="small" variant="outlined" color="error" onClick={() => onDelete(d)} disabled={deleteMut.isPending}>
              刪除
            </Button>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function Loading() {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
      <CircularProgress size={28} />
    </Box>
  )
}
