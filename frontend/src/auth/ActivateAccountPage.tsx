import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Link from "@mui/material/Link"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useEffect, useState } from "react"
import type { FormEvent } from "react"
import { useSearchParams } from "react-router-dom"

import { authApi } from "./authService"
import { ResetPasswordSchema } from "./schemas/resetPasswordSchema"
import { toApiError } from "../services/http"
import { getFieldErrors } from "../utils/zodUtils"

/**
 * 帳號啟用頁（US4 #67，管理者邀請信連結落點 /activate?token=xxx）。
 * 受邀者自設密碼啟用帳號：沿用重設密碼頁殼（置中卡片 + 新密碼 / 確認），複雜度驗證重用 ResetPasswordSchema。
 * 成功導回登入；token 無效 / 逾期顯示錯誤並引導洽管理者重寄（後端 DP_USER_003/004）。
 */
export function ActivateAccountPage() {
  const [searchParams] = useSearchParams()
  // 只在首次 render 擷取 token，隨即從網址移除，避免殘留於瀏覽器歷史 / Referer
  const [token] = useState(() => searchParams.get("token") ?? "")
  useEffect(() => {
    if (token) window.history.replaceState(null, "", window.location.pathname)
  }, [token])
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const parsed = ResetPasswordSchema.safeParse({ new_password: newPassword, confirm_password: confirmPassword })
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return

    setSubmitting(true)
    try {
      await authApi.activateAccount({ token, ...parsed.data })
      setDone(true)
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", p: 2 }}>
      <Card sx={{ width: 440, maxWidth: "100%", p: 4 }}>
        <Typography variant="h6" gutterBottom>
          歡迎加入，請設定密碼
        </Typography>
        {done ? (
          <Stack spacing={2}>
            <Alert severity="success">帳號已啟用，請以新密碼登入</Alert>
            <Link href="/" underline="hover">
              前往登入
            </Link>
          </Stack>
        ) : token === "" ? (
          <Alert severity="error">邀請連結無效，請洽管理者重寄</Alert>
        ) : (
          <form onSubmit={handleSubmit}>
            <Stack spacing={2}>
              {apiError !== null && <Alert severity="error">{apiError}</Alert>}
              <Typography variant="body2" color="text.secondary">
                系統管理者已為您建立帳號，設定密碼即可啟用並登入。
              </Typography>
              <TextField
                label="設定密碼"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                error={"new_password" in fieldErrors}
                helperText={fieldErrors.new_password ?? "至少 8 字元，含大小寫英文 / 數字 / 特殊符號至少 3 種"}
                fullWidth
                autoComplete="new-password"
              />
              <TextField
                label="確認密碼"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                error={"confirm_password" in fieldErrors}
                helperText={fieldErrors.confirm_password}
                fullWidth
                autoComplete="new-password"
              />
              <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
                設定密碼並啟用
              </Button>
            </Stack>
          </form>
        )}
      </Card>
    </Box>
  )
}