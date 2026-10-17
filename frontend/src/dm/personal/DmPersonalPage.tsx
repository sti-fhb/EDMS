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
import { useNavigate, useSearchParams } from "react-router-dom"

import type { ActivityEvent, DraftItem } from "./schemas"
import {
  DRAFT_KIND_LABELS,
  REVIEW_TYPE_LABELS,
  authorEventLabel,
  partyUnreachableText,
  reviewerEventLabel,
} from "./schemas"
import { personalApi } from "./personalService"
import { useActivity, useDrafts, usePersonalAccess } from "./usePersonal"
import { FilterCard } from "../../components/FilterCard"
import { ScreenHeader } from "../../components/ScreenHeader"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"
import { toApiError } from "../../services/http"

/**
 * 個人專區（US9 / DM04）：我的文件動態（狀態變動歷程）+ 草稿匣（**編輯者**）。
 * 動態呈現每次送審週期的每個狀態轉換（送審 → 退回 / 核准發布 / 撤回 / 廢止），時間新→舊；撰寫者對送審中項目可撤回。
 * 個人資料維護（姓名 / Email / 密碼）為另一入口，由平台 DP 提供（右上使用者選單），不在此頁。
 *
 * ⚠️ 本段原寫「草稿匣（編輯者 / 審核者）」，與 `spec_us9` FR-001 的「草稿匣（編輯者）」相反，
 * 已於 #657 更正。建草稿的端點全掛 `_ensure_editor`，純審核者不可能有草稿——頁籤對他恆空。
 */
export function DmPersonalPage() {
  const [searchParams] = useSearchParams()
  // 草稿匣僅編輯者可見（#657）。`can_access`（側欄入口：編輯者**或**審核者）與 `can_draft`
  // （頁內草稿匣頁籤：僅編輯者）是兩件事，後端分開回。
  //
  // 不會多一次請求、也不會有「頁籤閃一下才出現」：本頁的路由守門 `RequireDmPersonal`
  // 已以**同一個 query key**（`["dm-personal","access"]`）取過，且它的 `<Gate pending>`
  // 保證 `access` 載完才渲染本元件。`?? false` 只是型別上的預設值，正式環境走不到。
  // （測試直接 render 本元件、不經守門，那時才會短暫為 undefined。）
  const { data: access } = usePersonalAccess()
  const canDraft = access?.can_draft ?? false
  // 支援 ?tab=drafts 深連結（如編輯器續編後導回草稿匣）；預設「我的文件動態」。
  const [tab, setTab] = useState<"activity" | "drafts">(searchParams.get("tab") === "drafts" ? "drafts" : "activity")
  // 深連結 / 權限變動的收斂：非編輯者停在 drafts 會看到空白（MUI Tabs 找不到對應 value 亦會警告）。
  // 取用時就地折回 activity，而不是 useEffect setState——後者多一次 render 且會閃一下空白。
  const activeTab = tab === "drafts" && !canDraft ? "activity" : tab
  return (
    <Box>
      <ScreenHeader code="DM04" />
      <FilterCard>
        <Tabs value={activeTab} onChange={(_, v) => setTab(v)}>
          <Tab value="activity" label="我的文件動態" />
          {/* 條件渲染而非 disabled：對純審核者而言它不是「暫時不能按」，是不存在的功能 */}
          {canDraft && <Tab value="drafts" label="草稿匣" />}
        </Tabs>
      </FilterCard>
      {activeTab === "activity" ? <ActivityTab /> : <DraftsTab />}
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
      // ⛔ 不宣稱通知（#677）：`SUBMIT_WITHDRAWN` 自 seed 起 CHANNEL 即為 MSG（只站內、不寄信）；
      // 原指派審核者改由 DM02 簽核中心看到該項目自待處理清單消失。
      message.success("已撤回送審") // DM-MSG-DM04-005
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

/**
 * 兩視角表格共用欄寬（fixed layout），確保撰寫者 / 審核者兩表欄位上下對齊。
 *
 * ⚠️ **數量必須等於表頭欄位數**，順序亦須一一對應：
 * `文件名稱 / 類型 / 狀態 / 退回原因 / 對造人 / 時間 / 操作`
 *
 * #657 新增「退回原因」欄時（6→7 欄）漏了補這裡，第 7 欄「操作」因而分到寬度 0——
 * 「撤回送審」與「前往簽核中心」兩顆鈕在正常畫面上看不到，表格還多出橫向捲動（#679）。
 * 現已由 `DmPersonalPage.test.tsx` 的「colgroup 的欄寬數量必須等於表頭欄位數」守住。
 *
 * 「操作」留 12%（約 139px @1160px）：需容納「前往簽核中心」六個字不折行。
 */
const ACTIVITY_COLS = ["26%", "8%", "12%", "18%", "13%", "11%", "12%"]

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
              <TableCell>退回原因</TableCell>
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
  const unreachable = partyUnreachableText(event.party_unreachable, perspective)
  // 操作只掛在「當前送審中」事件（submitted 且 PENDING）
  const actionable = event.event_kind === "submitted" && event.status === "PENDING"

  const onWithdrawClick = () =>
    confirm({
      title: "確定撤回送審？",
      // ⛔ 不宣稱通知（#677 的第 8 處，漏接於 PR #686）：`SUBMIT_WITHDRAWN` 的 CHANNEL 為 `MSG`，
      // 而 `MSG` 不是「換一個管道送」而是「不送了」（平台無站內訊息佇列，見 data-model〈通知事件〉
      // 註記）——原指派審核者是從 DM02 簽核中心看到該項目消失、以及自己的動態出現「已被撤回」。
      content: "撤回後送審項目將回到草稿 / 已發布狀態。",
      okText: "確認撤回",
      onOk: () => onWithdraw?.(event.review_id),
    })

  return (
    <>
      <TableRow>
        <TableCell>{event.doc_name}</TableCell>
        <TableCell>{REVIEW_TYPE_LABELS[event.review_type] ?? event.review_type}</TableCell>
        <TableCell>
          <Chip size="small" color={label.tone} label={label.text} />
        </TableCell>
        {/* #554 / #679：本欄是審核者退回原因的站內讀取端——DOC_REJECT / OBS_REJECT 改站內後
            那封含原因的信不再寄出，不在此呈現的話就沒有任何讀取端。
            #679 起來源為 `DM_REVIEW.REJECT_REASON`（語意唯一），不再是 `REASON`。
            #657：原為狀態欄內的展開鈕 + 另起一列的 Collapse，改為正式欄位直接顯示全文。
            後端僅在 resolved + REJECTED 時給值，其餘為 null（送審事件的 REASON 在 OBSOLETE
            是「廢止申請原因」，語意不同、刻意不帶）。 */}
        <TableCell sx={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{event.reason ?? "—"}</TableCell>
        <TableCell>
          {event.party_name ?? "—"}
          {/* #395 D-2：對造人帳號不可達時說明原因——讓「知道」與「能做」落在同一個人身上。
              撰寫者本來就能撤回重送（撤回鈕就在同一列），缺的只是沒人告訴他該撤回。 */}
          {unreachable && (
            <Typography variant="caption" color="error" display="block">
              {unreachable}
            </Typography>
          )}
        </TableCell>
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
    </>
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
      title: "確定刪除此草稿？刪除後不可復原", // DM-MSG-DM04-004
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

/**
 * 「繼續編輯」入口。兩種父文件狀態會讓它失效，**原因不同**：
 *
 * - `OBSOLETE`：已廢止，續編無意義，只能刪草稿（終局）
 * - `PENDING_OBSOLETE`：廢止待簽核（#615）。入口原本仍可點，使用者進編輯器填完按儲存才被
 *   `DM_DOC_008` 擋下，而 `update_draft_version` 在 409 前不寫入 ⇒ **當次編輯內容直接遺失**。
 *   這條路徑本來就存在（他人發起廢止時也會），但 #600 讓「廢止此文件」在持有自己草稿時
 *   可按之後，變成**同一個人一鍵就能造成自己的資料遺失**。
 *
 * ⚠️ 這裡只擋入口；後端 `DM_DOC_008` 仍是最終守門，維持不動。
 */
function ContinueEditButton({ draft, onNavigate }: { draft: DraftItem; onNavigate: () => void }) {
  const lockReason =
    draft.doc_status === "OBSOLETE"
      ? "此文件已被廢止，無法繼續編輯，請刪除此草稿"
      : draft.doc_status === "PENDING_OBSOLETE"
        ? "此文件正在廢止簽核中，暫時無法繼續編輯；待簽核結果出爐後再處理此草稿"
        : null
  const button = (
    <Button size="small" variant="outlined" onClick={onNavigate} disabled={lockReason !== null}>
      繼續編輯
    </Button>
  )
  if (lockReason === null) return button
  // disabled Button 不觸發 hover 事件，需以 span 包裹讓 Tooltip 生效
  return (
    <Tooltip title={lockReason}>
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
