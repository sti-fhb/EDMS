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
 * 密碼重設頁（US3，信中連結落點 /reset-password?token=xxx）。
 * 沿用強制變更頁殼樣式（置中卡片 + 新密碼 / 確認）；Zod 驗複雜度 + 兩次一致，後端權威檢核。
 * 成功顯示 FORGOT-005 並導回登入；token 失效顯示 FORGOT-002（後端 DP_PWD_005）。
 */
export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  // 只在首次 render 擷取 token，隨即從網址移除，避免 token 殘留於瀏覽器歷史 / Referer（Security M-2）
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
      await authApi.resetPassword({ token, ...parsed.data })
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
          重設密碼
        </Typography>
        {done ? (
          <Stack spacing={2}>
            <Alert severity="success">密碼已更新，請以新密碼登入</Alert>
            <Link href="/" underline="hover">
              返回登入
            </Link>
          </Stack>
        ) : token === "" ? (
          <Alert severity="error">連結無效，請重新申請忘記密碼</Alert>
        ) : (
          <form onSubmit={handleSubmit}>
            <Stack spacing={2}>
              {apiError !== null && <Alert severity="error">{apiError}</Alert>}
              <TextField
                label="新密碼"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                error={"new_password" in fieldErrors}
                helperText={fieldErrors.new_password ?? "至少 8 字元，含大小寫英文 / 數字 / 特殊符號至少 3 種"}
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
                重設密碼
              </Button>
            </Stack>
          </form>
        )}
      </Card>
    </Box>
  )
}
