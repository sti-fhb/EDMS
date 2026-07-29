import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { FormEvent } from "react"
import { useNavigate } from "react-router-dom"

import { useAuth } from "./useAuth"
import { profileApi } from "../dp/user/profileService"
import { makeChangePasswordSchema } from "../dp/user/schemas/profileSchemas"
import { usePasswordPolicy } from "../hooks/usePasswordPolicy"
import { toApiError } from "../services/http"
import { getFieldErrors } from "../utils/zodUtils"

/**
 * 強制變更密碼頁殼（US1 §11 建閘 + 頁殼；US8 填實提交）。
 * 逾效期 / 初始密碼首登者被 password_gate（DP_AUTH_009）擋下並導向此頁，未完成變更不得離開。
 * 沿用同一 `PUT /me/password` 端點、仍需舊密碼（逾效期密碼仍有效可作舊密碼）；成功後清強制變更
 * 旗標放行至一般功能（不需重登）。提示數字依 PWD_POLICY 動態渲染（併 #77）。
 */
export function ForceChangePasswordShell() {
  const { logout, clearMustChangePwd } = useAuth()
  const navigate = useNavigate()
  const { policy, hint } = usePasswordPolicy()
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

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
      clearMustChangePwd() // 清旗標 → RootLayout 撤下頁殼、放行一般功能
      // 頁殼為覆蓋當前 URL 的 overlay，完成後導主頁（/）——否則會停在底下殘留的 URL（如 /profile）
      navigate("/")
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        position: "fixed",
        inset: 0,
        bgcolor: "background.default",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 2000,
        p: 2,
      }}
    >
      <Card sx={{ width: 440, maxWidth: "100%", p: 4 }}>
        <Typography variant="h6" gutterBottom>
          變更密碼
        </Typography>
        <Alert severity="warning" sx={{ mb: 2 }}>
          密碼已逾效期（或首次登入），請立即變更密碼
        </Alert>
        <form onSubmit={handleSubmit}>
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
            <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
              變更密碼
            </Button>
            <Button variant="text" onClick={() => void logout()}>
              返回登入
            </Button>
          </Stack>
        </form>
      </Card>
    </Box>
  )
}
