import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"

import { BlockerList } from "./BlockerList"
import type { BlockerNames, PublishBlocker } from "./surveySchemas"

interface BlockerSummaryProps {
  /** 清單上方的紅色說明。發布與再開課的文案不同，由呼叫端給。 */
  message: string
  blockers: PublishBlocker[]
  names: BlockerNames
}

/**
 * 發布檢核缺漏的呈現：紅色說明 + 缺漏清單（#509）。
 *
 * `PublishDialog` 與再開課的 `BlockerDialog` **共用這一段**。`PublishDialog` 不改用整個
 * `BlockerDialog`，是因為它的同一個視窗還要切換檢核中 / 條件已滿足 / 發布成功三態，
 * 缺漏只是其中一態——兩者能共用的就是這塊內容。
 *
 * ⛔ 只共用**呈現**，不共用資料：兩個呼叫端各自傳入自己那份 `blockers`（見
 * `CourseEditorPage` 的 `reopenBlockers` 宣告——併成一份會讓兩個視窗互相污染）。
 */
export function BlockerSummary({ message, blockers, names }: BlockerSummaryProps) {
  return (
    <Stack spacing={1}>
      <Alert severity="error">{message}</Alert>
      <BlockerList blockers={blockers} names={names} />
    </Stack>
  )
}

interface BlockerDialogProps extends BlockerSummaryProps {
  title: string
  onClose: () => void
}

/**
 * 「請求已失敗」的缺漏告知視窗（#509，再開課用）。
 *
 * ## 只有一顆「關閉」
 *
 * 跳出這個視窗時請求**已經失敗了**，它是事後告知，不是再問一次要不要送出。放一顆
 * 「確認再開課」會讓教師以為補齊前還能再按一次。
 *
 * ## 呼叫端以條件渲染掛載，不傳 `open`
 *
 * 常駐的 MUI `Dialog` 即使 `open={false}` 也參與 aria-hidden 的簿記，會讓同頁其他元素
 * 在測試裡查不到。故本元件掛上即開啟，關閉由呼叫端把它卸下。
 */
export function BlockerDialog({ title, onClose, ...summary }: BlockerDialogProps) {
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        <BlockerSummary {...summary} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>關閉</Button>
      </DialogActions>
    </Dialog>
  )
}
