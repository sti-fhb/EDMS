import ContentCopyIcon from "@mui/icons-material/ContentCopy"
import { Alert, Box, IconButton, Stack, Typography } from "@mui/material"

/**
 * 「課程變成學員看得見」之後的結果摘要——**帶入人數 + 邀請碼**。
 *
 * ## 為什麼抽成共用元件（#720）
 *
 * 發布（`PublishDialog`）與「更新並重開課」（`ReopenResultDialog`）顯示的是同一件事：
 * 這一下讓多少人進到課程裡、以及那串他可能從未抄下來的邀請碼。兩邊各寫一份的話，
 * 其中一邊日後調整文案或 0 人的處置，另一邊不會跟著動——而教師看到的會是同一個動作
 * 在兩個入口給出不同的說法。
 *
 * ⚠️ 兩處**唯一**的差別是第一句話（「已發布」vs「已重新開課」），由 `action` 帶入。
 * ⛔ 不要為了別的差異再加參數：差異變多就該是兩個元件，而不是一個長滿旗標的元件。
 */
export interface EnrolledResultSummaryProps {
  /** 動詞，嵌進「課程已{action}，…」。例：`"發布"`、`"重新開課"`。 */
  action: string
  invitedCount: number
  invitationCode: string | null
}

export function EnrolledResultSummary({ action, invitedCount, invitationCode }: EnrolledResultSummaryProps) {
  return (
    <Stack spacing={2}>
      {/* 帶入人數要據實顯示（#247）：0 通常代表課程掛的受訓對象沒有任何人符合，
          那是設定問題——等學員反映「看不到課」才發現就太晚了。 */}
      {invitedCount > 0 ? (
        <Alert severity="success">
          課程已{action}，已依受訓對象帶入 {invitedCount} 位學員。
        </Alert>
      ) : (
        <Alert severity="warning">
          課程已{action}，但沒有任何學員符合本課程的受訓對象。請確認受訓對象設定，或將下方邀請碼提供給學員。
        </Alert>
      )}
      <Box>
        <Typography variant="caption" color="text.secondary">
          課程邀請碼
        </Typography>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography variant="h5" fontFamily="monospace" letterSpacing={4}>
            {invitationCode}
          </Typography>
          <IconButton
            size="small"
            aria-label="複製邀請碼"
            onClick={() => void navigator.clipboard?.writeText(invitationCode ?? "")}
          >
            <ContentCopyIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Box>
    </Stack>
  )
}
