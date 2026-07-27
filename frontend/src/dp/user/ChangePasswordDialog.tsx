import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useState } from "react"
import type { FormEvent } from "react"

import { profileApi } from "./profileService"
import { makeChangePasswordSchema } from "./schemas/profileSchemas"
import { useNotification } from "../../contexts/NotificationContext"
import { usePasswordPolicy } from "../../hooks/usePasswordPolicy"
import { toApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"

/** 變更密碼對話框（US8）：舊 + 新 + 確認；提示依 PWD_POLICY 動態渲染；後端權威檢核複雜度 / 重複性。 */
export function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = useNotification()
  const { policy, hint } = usePasswordPolicy()
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const reset = () => {
    setOldPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setFieldErrors({})
    setApiError(null)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const schema = makeChangePasswordSchema(policy?.min_len, policy?.char_types)
    const parsed = schema.safeParse({
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    })
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return

    setSubmitting(true)
    try {
      await profileApi.changePassword(parsed.data)
      message.success("密碼已更新")
      handleClose()
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs">
      <DialogTitle>變更密碼</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2}>
            {apiError !== null && <Alert severity="error">{apiError}</Alert>}
            <TextField
              label="舊密碼"
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              error={"old_password" in fieldErrors}
              helperText={fieldErrors.old_password}
              fullWidth
              autoComplete="current-password"
            />
            <TextField
              label="新密碼"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              error={"new_password" in fieldErrors}
              helperText={fieldErrors.new_password ?? hint}
              fullWidth
              autoComplete="new-password"
            />
            <TextField
              label="確認新密碼"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              error={"confirm_password" in fieldErrors}
              helperText={fieldErrors.confirm_password}
              fullWidth
              autoComplete="new-password"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>取消</Button>
          <Button type="submit" variant="contained" disabled={submitting}>
            儲存
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
