import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Tabs from "@mui/material/Tabs"
import Tooltip from "@mui/material/Tooltip"
import Typography from "@mui/material/Typography"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import type { ActivityEvent, DraftItem } from "./schemas"
import {
  DRAFT_KIND_LABELS,
  REVIEW_TYPE_LABELS,
  authorEventLabel,
  reviewerEventLabel,
} from "./schemas"
import { personalApi } from "./personalService"
import { useActivity, useDrafts } from "./usePersonal"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"
import { toApiError } from "../../services/http"

/**
 * 個人專區（US9 / DM07）：我的文件動態（狀態變動歷程）+ 草稿匣（編輯者 / 審核者）。
 * 動態呈現每次送審週期的每個狀態轉換（送審 → 退回 / 核准發布 / 撤回 / 廢止），時間新→舊；撰寫者對送審中項目可撤回。
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

// ── 我的文件動態（狀態變動歷程）──────────────────────────

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
        <ActivitySection
          title="撰寫者視角（近 30 天）"
          partyHeader="指定審核者"
          events={data.author}
          perspective="author"
          onWithdraw={withdrawMut.mutate}
          busy={withdrawMut.isPending}
        />
      )}
      {hasReviewer && (
        <ActivitySection
          title="審核者視角（近 30 天）"
          partyHeader="送審者"
          events={data.reviewer}
          perspective="reviewer"
        />
      )}
    </Stack>
  )
}

// 兩視角表格共用欄寬（fixed layout），確保撰寫者 / 審核者兩表欄位上下對齊
const ACTIVITY_COLS = ["34%", "10%", "14%", "16%", "16%", "10%"]

function ActivitySection({
  title,
  partyHeader,
  events,
  perspective,
  onWithdraw,
  busy,
}: {
  title: string
  partyHeader: string
  events: ActivityEvent[]
  perspective: "author" | "reviewer"
  onWithdraw?: (reviewId: number) => void
  busy?: boolean
}) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        {title}
      </Typography>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small" sx={{ tableLayout: "fixed", minWidth: 720 }}>
          <colgroup>
            {ACTIVITY_COLS.map((w, i) => (
              <col key={i} style={{ width: w }} />
            ))}
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell>文件名稱</TableCell>
              <TableCell>類型</TableCell>
              <TableCell>狀態</TableCell>
              <TableCell>{partyHeader}</TableCell>
              <TableCell>時間</TableCell>
              <TableCell>操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {events.map((e) => (
              <ActivityRow
                key={`${e.review_id}-${e.event_kind}`}
                event={e}
                perspective={perspective}
                onWithdraw={onWithdraw}
                busy={busy}
              />
            ))}
          </TableBody>
        </Table>
      </Box>
    </Paper>
  )
}

function ActivityRow({
  event,
  perspective,
  onWithdraw,
  busy,
}: {
  event: ActivityEvent
  perspective: "author" | "reviewer"
  onWithdraw?: (reviewId: number) => void
  busy?: boolean
}) {
  const { confirm } = useNotification()
  const navigate = useNavigate()
  const label =
    perspective === "author" ? authorEventLabel(event) : reviewerEventLabel(event)
  // 操作只掛在「當前送審中」事件（submitted 且 PENDING）
  const actionable = event.event_kind === "submitted" && event.status === "PENDING"

  const onWithdrawClick = () =>
    confirm({
      title: "確定撤回送審？",
      content: "撤回後送審項目將回到草稿 / 已發布狀態，並通知原指派審核者。",
      okText: "確認撤回",
      onOk: () => onWithdraw?.(event.review_id),
    })

  return (
    <TableRow>
      <TableCell>{event.doc_name}</TableCell>
      <TableCell>{REVIEW_TYPE_LABELS[event.review_type] ?? event.review_type}</TableCell>
      <TableCell>
        <Chip size="small" color={label.tone} label={label.text} />
      </TableCell>
      <TableCell>{event.party_name ?? "—"}</TableCell>
      <TableCell>{formatDateTime(event.event_time)}</TableCell>
      <TableCell>
        {actionable && perspective === "author" && (
          <Button size="small" variant="outlined" color="error" onClick={onWithdrawClick} disabled={busy}>
            撤回送審
          </Button>
        )}
        {actionable && perspective === "reviewer" && (
          <Button
            size="small"
            variant="outlined"
            onClick={() => navigate(`/dm/review?reviewId=${event.review_id}`)}
          >
            前往簽核中心
          </Button>
        )}
        {!actionable && "—"}
      </TableCell>
    </TableRow>
  )
}

// ── 草稿匣 ────────────────────────────────────────────

function DraftsTab() {
  const { message, confirm } = useNotification()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data, isPending, isError } = useDrafts()

  const deleteMut = useMutation({
    mutationFn: (d: DraftItem) => personalApi.deleteDraft(d.version_id),
    onSuccess: (_res, d) => {
      message.success("草稿已刪除")
      qc.invalidateQueries({ queryKey: ["dm-personal", "drafts"] })
      // 失效該文件之續編 meta 與詳細快取，確保刪除後可立即再進編輯、不誤報「已有草稿」（#222）
      qc.invalidateQueries({ queryKey: ["dm-editor", "draft-meta", d.doc_id] })
      qc.invalidateQueries({ queryKey: ["dm-detail", d.doc_id] })
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
      onOk: () => deleteMut.mutate(d),
    })

  return (
    <Paper sx={{ p: 2 }}>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>文件名稱</TableCell>
              <TableCell>分類</TableCell>
              <TableCell>草稿類型</TableCell>
              <TableCell>最後編輯</TableCell>
              <TableCell>操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.map((d) => (
              <TableRow key={d.version_id}>
                <TableCell>
                  {d.doc_name}
                  {d.version_no && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      {d.version_no}
                    </Typography>
                  )}
                </TableCell>
                <TableCell>{d.category_code}</TableCell>
                <TableCell>
                  <Chip size="small" label={DRAFT_KIND_LABELS[d.kind]} />
                </TableCell>
                <TableCell>{formatDateTime(d.updated_date)}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1}>
                    <ContinueEditButton draft={d} onNavigate={() => navigate(`/dm/documents/${d.doc_id}/edit`)} />
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      onClick={() => onDelete(d)}
                      disabled={deleteMut.isPending}
                    >
                      刪除
                    </Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Paper>
  )
}

function ContinueEditButton({ draft, onNavigate }: { draft: DraftItem; onNavigate: () => void }) {
  const obsolete = draft.doc_status === "OBSOLETE" // 已廢止 → 不可續編，僅可刪除
  const button = (
    <Button size="small" variant="outlined" onClick={onNavigate} disabled={obsolete}>
      繼續編輯
    </Button>
  )
  if (!obsolete) return button
  // disabled Button 不觸發 hover 事件，需以 span 包裹讓 Tooltip 生效
  return (
    <Tooltip title="此文件已被廢止，無法繼續編輯，請刪除此草稿">
      <span>{button}</span>
    </Tooltip>
  )
}

function Loading() {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
      <CircularProgress size={28} />
    </Box>
  )
}
