import ArchiveIcon from "@mui/icons-material/Archive"
import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import DownloadIcon from "@mui/icons-material/Download"
import EditIcon from "@mui/icons-material/Edit"
import HistoryIcon from "@mui/icons-material/History"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Collapse from "@mui/material/Collapse"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableRow from "@mui/material/TableRow"
import Tooltip from "@mui/material/Tooltip"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { ReactNode } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { downloadVersionFile, previewVersionFile } from "./detailService"
import type { DetailResponse, VersionItem } from "./schemas"
import { useDetail, useVersions } from "./useDetail"
import { useNotification } from "../../contexts/NotificationContext"

/** 檔案存取失敗訊息：缺檔（404）明確提示「查無檔案」，避免誤導為系統故障。 */
function fileErrorMessage(err: unknown, action: string): string {
  const status = (err as { response?: { status?: number } } | null)?.response?.status
  if (status === 404) return "查無檔案，可能已被移除，請聯絡管理者"
  return `檔案${action}失敗，請稍後再試`
}

/**
 * 文件詳細頁瀏覽（US4 / DM02）：標題列 + 右側資訊面板 + 檔案區（PDF/圖片預覽、Office 僅下載）+
 * 版本歷程抽屜（目前版可下載、舊版僅預覽）+（編輯者）編輯/廢止入口 + 已廢止 read-only 模式。
 */
export function DmDetailPage() {
  const { docId = "" } = useParams()
  const navigate = useNavigate()
  const { message } = useNotification()
  const { data: detail, isPending, isError } = useDetail(docId)
  const [historyOpen, setHistoryOpen] = useState(false)

  const readOnly = detail?.is_obsolete ?? false
  // 已廢止：版本歷程自動展開
  const versionsEnabled = historyOpen || readOnly
  const { data: versions } = useVersions(docId, versionsEnabled)

  const onDownload = async (versionId: number, filename: string) => {
    try {
      await downloadVersionFile(docId, versionId, filename)
    } catch (err) {
      message.error(fileErrorMessage(err, "下載"))
    }
  }
  const onPreview = async (versionId: number) => {
    try {
      await previewVersionFile(docId, versionId)
    } catch (err) {
      message.error(fileErrorMessage(err, "預覽"))
    }
  }

  if (isPending) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", p: 6 }}>
        <CircularProgress />
      </Box>
    )
  }
  if (isError || !detail) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">查無此文件或無權存取。</Alert>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* 標題列（僅識別 + 狀態） */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5">{detail.doc_name}</Typography>
        <Stack direction="row" spacing={2} sx={{ mt: 0.5 }} alignItems="center">
          <Typography variant="caption" color="text.secondary">
            DOC_ID: {detail.doc_id}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            目前版本：{detail.current_version_no ?? "—"}
          </Typography>
        </Stack>
      </Box>

      {/* 已廢止 read-only banner */}
      {readOnly && (
        <Alert severity="error" icon={<ArchiveIcon />} sx={{ mb: 2 }}>
          本文件已<strong>廢止</strong>，僅供稽核查閱；所有版本僅可預覽、不開放下載。
          {detail.obsolete_info && (
            <Typography variant="caption" sx={{ display: "block", mt: 0.5 }}>
              廢止時間：{detail.obsolete_info.obsolete_time?.slice(0, 10) ?? "—"} ｜ 申請人：
              {detail.obsolete_info.applicant_name ?? detail.obsolete_info.applicant_id} ｜ 核准者：
              {detail.obsolete_info.approver_name ?? "—"} ｜ 廢止原因：{detail.obsolete_info.reason ?? "—"}
              {detail.obsolete_info.has_attachment && "　｜ 廢止附件（如需請聯絡管理者）"}
            </Typography>
          )}
        </Alert>
      )}

      {/* 操作列 */}
      <Paper sx={{ p: 1.5, mb: 2 }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
          <Button
            size="small"
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate("/dm/library")}
          >
            返回文件庫
          </Button>
          <Button
            size="small"
            variant="outlined"
            startIcon={<HistoryIcon />}
            onClick={() => setHistoryOpen((v) => !v)}
          >
            版本歷程
          </Button>
          {/* 編輯者入口：送審中 / 廢止待簽核時灰階 + 提示原因（非隱藏，FR-005）；已廢止則整段不顯示 */}
          {detail.is_editor && !readOnly && (
            <>
              <LockableButton
                label="編輯新版本"
                icon={<EditIcon />}
                disabled={!detail.can_edit}
                reason={detail.edit_lock_reason}
                onClick={() => navigate(`/dm/documents/${docId}/edit`)}
              />
              {/* 彈性間隔：把「廢止此文件」推到橫幅最右邊（比 ml:auto 更不受 Stack spacing 影響） */}
              <Box sx={{ flexGrow: 1 }} />
              <LockableButton
                label="廢止此文件"
                icon={<ArchiveIcon />}
                color="error"
                disabled={!detail.can_edit}
                reason={detail.edit_lock_reason}
                onClick={() => navigate(`/dm/documents/${docId}/obsolete`)}
              />
            </>
          )}
        </Stack>
      </Paper>

      {/* 文件檔案 + 文件資訊（read-only 隱藏整段） */}
      {!readOnly && (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "2fr 1fr" }, gap: 2, mb: 2 }}>
          <FileArea detail={detail} onDownload={onDownload} onPreview={onPreview} />
          <InfoPanel detail={detail} />
        </Box>
      )}

      {/* 版本歷程抽屜 */}
      <Collapse in={versionsEnabled} unmountOnExit>
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            <HistoryIcon fontSize="small" sx={{ verticalAlign: "middle", mr: 0.5 }} />
            版本歷程
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              {readOnly ? "（已廢止：所有版本僅供預覽）" : "（目前版本可下載；舊版本僅供預覽）"}
            </Typography>
          </Typography>
          <Stack divider={<Divider />} spacing={1.5}>
            {(versions ?? []).map((v) => (
              <VersionRow key={v.version_id} v={v} readOnly={readOnly} onDownload={onDownload} onPreview={onPreview} />
            ))}
          </Stack>
        </Paper>
      </Collapse>
    </Box>
  )
}

function FileArea({
  detail,
  onDownload,
  onPreview,
}: {
  detail: DetailResponse
  onDownload: (versionId: number, filename: string) => void
  onPreview: (versionId: number) => void
}) {
  const f = detail.file
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        文件檔案
      </Typography>
      {!f ? (
        <Typography variant="body2" color="text.secondary">
          尚無檔案。
        </Typography>
      ) : (
        <Box
          sx={{
            textAlign: "center",
            py: 4,
            bgcolor: "action.hover",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
          }}
        >
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {f.file_name}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
            {(f.file_size / 1024).toFixed(0)} KB ｜ {f.uploaded_at?.slice(0, 10) ?? ""}
          </Typography>
          <Stack direction="row" spacing={1} justifyContent="center">
            {f.previewable ? (
              <Button size="small" variant="outlined" startIcon={<VisibilityIcon />} onClick={() => onPreview(f.version_id)}>
                預覽
              </Button>
            ) : (
              <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                此檔案為 Office 格式，無法線上預覽，請下載原檔以本機應用程式開啟
              </Typography>
            )}
            <Button
              size="small"
              variant="contained"
              startIcon={<DownloadIcon />}
              onClick={() => onDownload(f.version_id, f.file_name)}
            >
              下載
            </Button>
          </Stack>
        </Box>
      )}
    </Paper>
  )
}

function InfoPanel({ detail }: { detail: DetailResponse }) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        文件資訊
      </Typography>
      <Table size="small">
        <TableBody>
          <InfoRow label="分類" value={<Chip size="small" label={detail.category_name} />} />
          <InfoRow label="作者" value={detail.author_name ?? detail.author_id} />
          <InfoRow label="核准者" value={detail.approver_name ?? "—"} />
          <InfoRow label="發布時間" value={detail.published_date?.slice(0, 16).replace("T", " ") ?? "—"} />
          <InfoRow
            label="標籤"
            value={
              <Typography variant="caption" color="text.secondary">
                {detail.tags.length > 0 ? detail.tags.join("、") : "—"}
              </Typography>
            }
          />
          {detail.func_code && (
            <InfoRow label="關聯作業項目" value={`${detail.func_code} — ${detail.func_name ?? ""}`} />
          )}
        </TableBody>
      </Table>
    </Paper>
  )
}

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <TableRow>
      {/* 欄位名稱：主要文字色（同「文件資訊」標題）+ 右側直線分隔 + 底線 */}
      <TableCell
        sx={{
          width: "35%",
          color: "text.primary",
          fontWeight: 500,
          borderRight: 1,
          borderBottom: 1,
          borderColor: "divider",
          py: 0.75,
        }}
      >
        {label}
      </TableCell>
      <TableCell sx={{ borderBottom: 1, borderColor: "divider", py: 0.75 }}>{value}</TableCell>
    </TableRow>
  )
}

function VersionRow({
  v,
  readOnly,
  onDownload,
  onPreview,
}: {
  v: VersionItem
  readOnly: boolean
  onDownload: (versionId: number, filename: string) => void
  onPreview: (versionId: number) => void
}) {
  // 目前版且非廢止 → 可下載；否則僅預覽
  const canDownload = v.is_current && !readOnly
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Box>
          <Typography variant="body2" component="span" sx={{ fontWeight: 600 }}>
            {v.version_no}
          </Typography>
          <Chip
            size="small"
            label={v.is_current ? "目前發布版本" : "已被取代"}
            color={v.is_current ? "success" : "default"}
            sx={{ ml: 1 }}
          />
        </Box>
        <Stack direction="row" spacing={1}>
          {v.previewable && (
            <Button size="small" variant="text" startIcon={<VisibilityIcon />} onClick={() => onPreview(v.version_id)}>
              預覽
            </Button>
          )}
          {canDownload && (
            <Button
              size="small"
              variant="text"
              startIcon={<DownloadIcon />}
              onClick={() => onDownload(v.version_id, v.file_name)}
            >
              下載
            </Button>
          )}
        </Stack>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
        {v.author_name ?? v.author_id} | {v.published_date?.slice(0, 10) ?? "—"} 發布
        {v.approver_name && ` | 核准者：${v.approver_name}`}
      </Typography>
      <Typography variant="caption" sx={{ display: "block" }}>
        {v.change_summary}
      </Typography>
    </Box>
  )
}

/**
 * 編輯者動作入口按鈕：失效時灰階（disabled）並以 tooltip 提示原因（送審中 / 廢止待簽核），非隱藏。
 * disabled 的 MUI Button 不觸發 tooltip 事件，故以 span 包裹作為事件與 flex 佈局載體。
 */
function LockableButton({
  label,
  icon,
  disabled,
  reason,
  onClick,
  color,
}: {
  label: string
  icon: ReactNode
  disabled: boolean
  reason: string | null
  onClick: () => void
  color?: "error"
}) {
  return (
    <Tooltip title={disabled && reason ? reason : ""}>
      <Box component="span" sx={{ display: "inline-flex" }}>
        <Button size="small" variant="outlined" color={color} startIcon={icon} disabled={disabled} onClick={onClick}>
          {label}
        </Button>
      </Box>
    </Tooltip>
  )
}