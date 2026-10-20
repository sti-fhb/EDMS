import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import { BlockerSummary } from "./BlockerDialog"
import { EnrolledResultSummary } from "./EnrolledResultSummary"
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
  /** `chapter_id` → 章節名稱。供 `CHAPTER_EMPTY` 指出是哪一章（#358 第 3 項）。 */
  chapterNames: Record<number, string>
  /** item_id → **所屬章節**名稱（`ITEM_NO_TITLE` 用；該項目自己沒有名稱）。 */
  itemChapterNames: Record<number, string>
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
  chapterNames,
  itemChapterNames,
  onPublish,
  onClose,
}: PublishDialogProps) {
  const canPublish = !checking && blockers.length === 0
  /**
   * 有缺漏時只留「關閉」（#558）：這個視窗此時是**告知**，關掉之後缺漏處會標紅框。
   * 一顆按不下去的「確認發布」只會讓教師以為還差一步，比照再開課的 `BlockerDialog`。
   */
  const blocked = !result && !checking && blockers.length > 0

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{result ? "課程已發布" : "發布課程"}</DialogTitle>
      <DialogContent dividers>
        {result ? (
          // #720：結果摘要抽成共用元件，與「更新並重開課」的結果視窗同一份（見該元件）
          <EnrolledResultSummary
            action="發布"
            invitedCount={result.invited_count}
            invitationCode={result.invitation_code}
            // 發布的 0 ＝ 真的沒人符合受訓對象，是**設定問題**：等學員反映「看不到課」
            // 才發現就太晚了，所以用 warning 並要教師去查（#247）。
            emptySeverity="warning"
            emptyMessage="課程已發布，但沒有任何學員符合本課程的受訓對象。請確認受訓對象設定，或將下方邀請碼提供給學員。"
          />
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
              發布後課程狀態轉為「已發布」，系統會產生 8 碼邀請碼並依受訓對象自動邀請對應學員。
              起始時間未到前，學員可在「我的課程」看到這門課程，但標示尚未開放、無法進入學習。
            </Typography>
          </Stack>
        ) : (
          <BlockerSummary
            context="publish"
            message="發布條件未滿足，請先補齊以下項目。關閉本視窗後，缺漏處會以紅框標示。"
            blockers={blockers}
            names={{ quiz: quizNames, chapter: chapterNames, itemChapter: itemChapterNames }}
          />
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{result || blocked ? "關閉" : "取消"}</Button>
        {!result && !blocked && (
          <Button variant="contained" disabled={!canPublish || publishing} onClick={onPublish}>
            確認發布
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
