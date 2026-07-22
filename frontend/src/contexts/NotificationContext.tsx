import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"
import Snackbar from "@mui/material/Snackbar"
import { createContext, useCallback, useContext, useMemo, useState } from "react"
import type { ReactNode } from "react"

/** 訊息嚴重度，對齊 spec 五類訊息（成功 / 錯誤 / 警告 / 提示）。 */
type Severity = "success" | "error" | "warning" | "info"

interface MessageApi {
  success: (text: string) => void
  error: (text: string) => void
  warning: (text: string) => void
  info: (text: string) => void
}

interface ConfirmOptions {
  title: string
  content: ReactNode
  okText?: string
  cancelText?: string
  /** 危險操作（如停用）以警示色呈現確認鈕。 */
  danger?: boolean
  /** 按下確認後執行；可為 async，執行期間確認鈕顯示 loading，成功後自動關閉。 */
  onOk: () => void | Promise<void>
}

export interface NotificationApi {
  message: MessageApi
  confirm: (options: ConfirmOptions) => void
}

const NotificationContext = createContext<NotificationApi | undefined>(undefined)

interface SnackbarState {
  open: boolean
  text: string
  severity: Severity
}

interface ConfirmState extends ConfirmOptions {
  open: boolean
  loading: boolean
}

const INITIAL_SNACKBAR: SnackbarState = { open: false, text: "", severity: "info" }

/**
 * 全域通知與確認對話框 Provider。
 *
 * 取代原生 `alert` / `confirm`：`message.*` 以 Snackbar 呈現短暫提示，
 * `confirm` 以 Dialog 呈現二次確認（支援 async onOk 與 danger 樣式）。
 */
export function NotificationProvider({ children }: { children: ReactNode }) {
  const [snackbar, setSnackbar] = useState<SnackbarState>(INITIAL_SNACKBAR)
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)

  const showMessage = useCallback((text: string, severity: Severity) => {
    setSnackbar({ open: true, text, severity })
  }, [])

  const message = useMemo<MessageApi>(
    () => ({
      success: (text) => showMessage(text, "success"),
      error: (text) => showMessage(text, "error"),
      warning: (text) => showMessage(text, "warning"),
      info: (text) => showMessage(text, "info"),
    }),
    [showMessage],
  )

  const confirm = useCallback((options: ConfirmOptions) => {
    setConfirmState({ ...options, open: true, loading: false })
  }, [])

  const closeConfirm = useCallback(() => {
    // 先關閉再清空，避免關閉動畫期間內容跳掉
    setConfirmState((prev) => (prev ? { ...prev, open: false } : null))
  }, [])

  const handleConfirmOk = useCallback(async () => {
    if (confirmState === null) return
    setConfirmState((prev) => (prev ? { ...prev, loading: true } : null))
    try {
      await confirmState.onOk()
      closeConfirm()
    } catch {
      // onOk 失敗（如 API 錯誤）由呼叫端自行以 message.error 呈現；此處僅解除 loading、保留對話框
      setConfirmState((prev) => (prev ? { ...prev, loading: false } : null))
    }
  }, [confirmState, closeConfirm])

  const api = useMemo<NotificationApi>(() => ({ message, confirm }), [message, confirm])

  return (
    <NotificationContext.Provider value={api}>
      {children}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={snackbar.severity}
          variant="filled"
          onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
        >
          {snackbar.text}
        </Alert>
      </Snackbar>
      <Dialog open={confirmState?.open ?? false} onClose={closeConfirm}>
        <DialogTitle>{confirmState?.title}</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">{confirmState?.content}</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeConfirm} disabled={confirmState?.loading}>
            {confirmState?.cancelText ?? "取消"}
          </Button>
          <Button
            onClick={handleConfirmOk}
            color={confirmState?.danger ? "warning" : "primary"}
            variant="contained"
            disabled={confirmState?.loading}
          >
            {confirmState?.okText ?? "確認"}
          </Button>
        </DialogActions>
      </Dialog>
    </NotificationContext.Provider>
  )
}

/** 取得全域通知 API；必須在 <NotificationProvider> 內使用。 */
export function useNotification(): NotificationApi {
  const ctx = useContext(NotificationContext)
  if (ctx === undefined) {
    throw new Error("useNotification 必須在 <NotificationProvider> 內使用")
  }
  return ctx
}
