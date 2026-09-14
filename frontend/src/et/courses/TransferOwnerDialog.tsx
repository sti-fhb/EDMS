import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { TRANSFER_REASON_MAX_LENGTH, type TeacherOption } from "./schemas"

interface TransferOwnerDialogProps {
  open: boolean
  submitting: boolean
  /** 課程名稱——視窗要說清楚正在轉讓哪一門課。 */
  courseName: string
  /** 目前擁有者顯示名稱；查無姓名時後端回 null，此處以 ID 兜底由頁面處理。 */
  currentOwnerName: string
  /** 可接收的教師（已排除現任擁有者，由頁面過濾）。 */
  teachers: TeacherOption[]
  /** 後端回的錯誤訊息（接收者不具教師角色、已是擁有者等）；`null` = 無錯誤。 */
  error: string | null
  onSubmit: (toOwnerId: string, reason: string) => void
  onClose: () => void
}

/**
 * 轉讓課程擁有者視窗（ET-13 / US1 補強 / #303）。
 *
 * ## 沒有 wireframe
 *
 * `grep -c '轉讓' docs/wireframes/et/index.html` = 0——本功能只在 `spec.md` §擁有權判定
 * 與 `plan.md` 的取捨紀錄中被描述，沒有畫面設計。版面沿用 ET02 既有元件的形狀
 * （比照 `ReopenCourseDialog`），不自創新樣式。
 *
 * ## 視窗本身即確認步驟
 *
 * 不再疊第二層 `confirm`：使用者已經選了人、打了原因、讀了不可復原的警語才會按送出。
 * 多一層「你確定嗎」只會訓練人閉著眼睛按下一步。比照 `ReopenCourseDialog`。
 *
 * ## 為何送出鈕在有錯誤時仍可按
 *
 * 錯誤多半是「選錯人」，使用者改完選項就該能再送。disable 會讓他只能關掉視窗重開，
 * 而畫面上沒有任何提示說要那樣做。比照 `ReopenCourseDialog` 對缺漏的處理。
 */
export function TransferOwnerDialog({
  open,
  submitting,
  courseName,
  currentOwnerName,
  teachers,
  error,
  onSubmit,
  onClose,
}: TransferOwnerDialogProps) {
  const [receiver, setReceiver] = useState<TeacherOption | null>(null)
  const [reason, setReason] = useState("")
  const [errors, setErrors] = useState<{ receiver?: string; reason?: string }>({})

  const handleClose = () => {
    setReceiver(null)
    setReason("")
    setErrors({})
    onClose()
  }

  const handleSubmit = () => {
    const next: { receiver?: string; reason?: string } = {}
    if (!receiver) next.receiver = "請選擇接收教師"
    // 全空白等同未填——與後端 `_reason_not_blank` 同一判定
    if (!reason.trim()) next.reason = "請填寫轉讓原因"

    setErrors(next)
    if (Object.keys(next).length > 0) return
    onSubmit(receiver!.user_id, reason.trim())
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>轉讓課程擁有者</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}

          <Stack spacing={0.5}>
            <Typography variant="body2" color="text.secondary">
              課程：{courseName}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              目前擁有者：{currentOwnerName}
            </Typography>
          </Stack>

          <Autocomplete
            size="small"
            options={teachers}
            value={receiver}
            getOptionLabel={(o) => `${o.user_name}（${o.user_id}）`}
            isOptionEqualToValue={(a, b) => a.user_id === b.user_id}
            onChange={(_, next) => setReceiver(next)}
            noOptionsText="沒有可接收的教師"
            renderInput={(params) => (
              <TextField
                {...params}
                label="接收教師"
                required
                error={Boolean(errors.receiver)}
                helperText={errors.receiver}
              />
            )}
          />

          <TextField
            label="轉讓原因"
            required
            size="small"
            fullWidth
            multiline
            rows={2}
            value={reason}
            error={Boolean(errors.reason)}
            // 字數提示常駐——上限與後端 `TRANSFER_REASON_MAX_LEN` 同值
            helperText={errors.reason ?? `${reason.length} / ${TRANSFER_REASON_MAX_LENGTH}`}
            slotProps={{ htmlInput: { maxLength: TRANSFER_REASON_MAX_LENGTH } }}
            onChange={(e) => setReason(e.target.value)}
          />

          {/*
            警語常駐而非只在送出時出現：轉讓會改變一門課程的歸屬，且會寫進 append-only
            的稽核紀錄。使用者在按下去之前就該知道這兩件事。
          */}
          <Alert severity="warning">
            轉讓後原擁有者僅可閱覽此課程，無法再編輯。本操作會寫入稽核紀錄，
            但可由管理者再次轉讓回去。
          </Alert>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>取消</Button>
        <Button variant="contained" color="warning" disabled={submitting} onClick={handleSubmit}>
          確認轉讓
        </Button>
      </DialogActions>
    </Dialog>
  )
}
