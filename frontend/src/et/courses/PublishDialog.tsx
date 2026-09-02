import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline"
import ContentCopyIcon from "@mui/icons-material/ContentCopy"
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import { BLOCKER_HINT } from "./surveySchemas"
import type { PublishBlocker, PublishResult } from "./surveySchemas"

interface PublishDialogProps {
  open: boolean
  /** 預檢進行中。 */
  checking: boolean
  publishing: boolean
  blockers: PublishBlocker[]
  /** 發布成功後之結果——有值時視窗切換為成功態。 */
  result: PublishResult | null
  /** 缺漏項目所指向的測驗名稱（`target_id` → 名稱），由頁面自課程詳細對照後傳入。 */
  quizNames: Record<number, string>
  onPublish: () => void
  onClose: () => void
}

/**
 * 發布檢核與結果視窗（US3 / #204）。
 *
 * ## 為何缺漏訊息要在前端補「去哪裡修」
 *
 * 後端回的 `message` 是靜態文案（如「課程至少須掛 1 個受訓單位標籤」）——它不該知道
 * 前端把標籤放在哪個區塊。「請於『基本資料』選擇受訓單位標籤」這種導引屬 UI 知識，
 * 由 `BLOCKER_HINT` 在前端補。
 *
 * ## 測驗名稱由前端對照
 *
 * 後端只回 `target_id`，不回測驗名稱——名稱是使用者輸入，回摻進錯誤訊息等於原樣吐回
 * （對齊 `sti-error-codes`）。頁面本來就有課程詳細，自行對照即可。
 */
export function PublishDialog({
  open,
  checking,
  publishing,
  blockers,
  result,
  quizNames,
  onPublish,
  onClose,
}: PublishDialogProps) {
  const canPublish = !checking && blockers.length === 0

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{result ? "課程已發布" : "發布課程"}</DialogTitle>
      <DialogContent dividers>
        {result ? (
          <Stack spacing={2}>
            {/* 帶入人數要據實顯示（#247）：0 通常代表課程掛的標籤沒有任何人掛上，
                那是設定問題——等學員反映「看不到課」才發現就太晚了。 */}
            {result.invited_count > 0 ? (
              <Alert severity="success">課程已發布，已依受訓單位標籤帶入 {result.invited_count} 位學員。</Alert>
            ) : (
              <Alert severity="warning">
                課程已發布，但沒有任何學員符合本課程的受訓單位標籤。請確認標籤設定，或將下方邀請碼提供給學員。
              </Alert>
            )}
            <Box>
              <Typography variant="caption" color="text.secondary">
                課程邀請碼（發布後永久不可變更）
              </Typography>
              <Stack direction="row" alignItems="center" spacing={1}>
                <Typography variant="h5" fontFamily="monospace" letterSpacing={4}>
                  {result.invitation_code}
                </Typography>
                <IconButton
                  size="small"
                  aria-label="複製邀請碼"
                  onClick={() => void navigator.clipboard?.writeText(result.invitation_code)}
                >
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Stack>
            </Box>
          </Stack>
        ) : checking ? (
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <CircularProgress size={20} />
            <Typography variant="body2">檢核中…</Typography>
          </Stack>
        ) : canPublish ? (
          <Stack spacing={1.5}>
            <Alert severity="success" icon={<CheckCircleOutlineIcon fontSize="inherit" />}>
              發布條件皆已滿足。
            </Alert>
            <Typography variant="body2" color="text.secondary">
              發布後課程狀態轉為「已發布」，系統會產生 8 碼邀請碼並依受訓單位標籤自動邀請對應學員。
              起始時間未到前，學員端不會看到這門課程。
            </Typography>
          </Stack>
        ) : (
          <Stack spacing={1}>
            <Alert severity="error">發布條件未滿足，請先補齊以下項目。</Alert>
            <List dense disablePadding>
              {blockers.map((blocker, index) => (
                // 以索引補進 key：同一 `code` 可能對應多個測驗（`target_id` 不同），
                // 單用 code 會重複；code + target_id 已足夠唯一，索引僅作保險。
                <ListItem key={`${blocker.code}-${blocker.target_id ?? index}`} disableGutters>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    <ErrorOutlineIcon color="error" fontSize="small" />
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      blocker.target_id !== null && quizNames[blocker.target_id]
                        ? `${blocker.message}（測驗「${quizNames[blocker.target_id]}」）`
                        : blocker.message
                    }
                    secondary={BLOCKER_HINT[blocker.code]}
                  />
                </ListItem>
              ))}
            </List>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{result ? "關閉" : "取消"}</Button>
        {!result && (
          <Button variant="contained" disabled={!canPublish || publishing} onClick={onPublish}>
            確認發布
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
