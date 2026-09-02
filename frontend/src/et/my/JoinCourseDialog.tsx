import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { INVITATION_CODE_LENGTH, invitationCodeSchema } from "./myCoursesSchemas"
import type { JoinPreview } from "./myCoursesSchemas"
import { myCoursesApi } from "./myCoursesService"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"

interface Props {
  open: boolean
  onClose: () => void
  /** 加入成功。`pendingOpen` 為 true 時課程尚未開放，清單不會出現該課程（AC 4）。 */
  onJoined: (courseId: number, pendingOpen: boolean) => void
  /** 已加入之課程——直接導向，不重複加入（AC 10）。 */
  onAlreadyJoined: (courseId: number) => void
}

/**
 * ET04 加入新課程（AC 5～AC 10）。
 *
 * 三態：**輸入** → **預覽** → 加入。預覽是 AC 8 明訂的一步（「顯示課程資訊，學員
 * 確認後加入」），不是可省略的中間頁——學員拿到的是一串數字，加入前沒有任何線索
 * 知道那是哪門課。
 *
 * 錯誤以 **inline `Alert`** 呈現而非 Snackbar：使用者的注意力在這個視窗裡，而且
 * 「邀請碼無效」要與輸入框並存才看得出是哪一次輸入錯了。
 */
export function JoinCourseDialog({ open, onClose, onJoined, onAlreadyJoined }: Props) {
  const [code, setCode] = useState("")
  const [preview, setPreview] = useState<JoinPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const codeValid = invitationCodeSchema.safeParse(code).success

  function reset() {
    setCode("")
    setPreview(null)
    setError(null)
    setBusy(false)
  }

  function handleClose() {
    reset()
    onClose()
  }

  /**
   * 只接受數字並截斷至 8 碼——在輸入端擋掉，而不是等送出才報錯。
   *
   * 貼上帶空白的邀請碼（從通訊軟體複製很常見）也能用：非數字字元一律濾掉。
   */
  function handleChange(raw: string) {
    setCode(raw.replace(/[^0-9]/g, "").slice(0, INVITATION_CODE_LENGTH))
    setError(null)
  }

  async function handlePreview() {
    setBusy(true)
    setError(null)
    try {
      const result = await myCoursesApi.preview(code)
      if (result.already_joined) {
        // 不進預覽——AC 10 要的是直接導向該課程。
        handleClose()
        onAlreadyJoined(result.course_id)
        return
      }
      setPreview(result)
    } catch (err) {
      setError(toApiError(err).errorMessage)
    } finally {
      setBusy(false)
    }
  }

  async function handleJoin() {
    setBusy(true)
    setError(null)
    try {
      const result = await myCoursesApi.join(code)
      handleClose()
      onJoined(result.course_id, result.pending_open)
    } catch (err) {
      // 加入階段才失敗（課程剛被關閉、剛被移除）——退回輸入態並顯示原因，
      // 停在預覽畫面會讓「確認加入」看起來像沒反應。
      setPreview(null)
      setError(toApiError(err).errorMessage)
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>加入新課程</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          {preview ? (
            <PreviewBody preview={preview} />
          ) : (
            <TextField
              autoFocus
              label="邀請碼"
              value={code}
              onChange={(e) => handleChange(e.target.value)}
              helperText={`請輸入教師提供的 ${INVITATION_CODE_LENGTH} 碼數字邀請碼`}
              slotProps={{ htmlInput: { inputMode: "numeric", maxLength: INVITATION_CODE_LENGTH } }}
              fullWidth
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        {preview ? (
          <>
            <Button onClick={() => setPreview(null)} disabled={busy}>
              上一步
            </Button>
            <Button variant="contained" onClick={handleJoin} disabled={busy}>
              確認加入
            </Button>
          </>
        ) : (
          <>
            <Button onClick={handleClose} disabled={busy}>
              取消
            </Button>
            <Button variant="contained" onClick={handlePreview} disabled={!codeValid || busy}>
              查詢
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  )
}

function PreviewBody({ preview }: { preview: JoinPreview }) {
  const pendingOpen = preview.open_start_at !== null && new Date(preview.open_start_at) > new Date()

  return (
    <Stack spacing={1}>
      <Typography variant="h6">{preview.course_name}</Typography>
      <Typography variant="body2" color="text.secondary">
        教師：{preview.owner_name ?? "—"}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        章節數：{preview.chapter_count}
      </Typography>
      {pendingOpen && (
        // SA Q2 裁示 A：允許加入，但要講清楚。不提示的話學員加入成功卻在清單看不到
        // 課程（AC 4），會以為加入失敗而反覆重試。
        <Alert severity="info">本課程將於 {formatDateTime(preview.open_start_at)} 開放學習</Alert>
      )}
    </Stack>
  )
}
