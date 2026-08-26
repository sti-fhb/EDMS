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

import { AUTH_BG_GRADIENT } from "./authBackground"
import { authApi } from "./authService"
import { makeResetPasswordSchema } from "./schemas/resetPasswordSchema"
import { usePasswordPolicy } from "../hooks/usePasswordPolicy"
import { toApiError } from "../services/http"
import { getFieldErrors } from "../utils/zodUtils"

/**
 * 註冊驗證落點頁（US2，驗證信連結落點 /verify-email?token=xxx）。
 *
 * **自 #212 起本頁改為「設定密碼」表單**，不再是「進來就自動驗證」的結果頁：註冊時不收密碼，
 * 密碼由點連結的本人在此當場設定。原設計把密碼存在待驗證列，使任何人可用他人 Email 註冊並
 * 填自己的密碼，受害者點下（來自組織網域、格式正確的）驗證信後，帳號就以攻擊者的密碼建立。
 *
 * 與 US4 的 ActivateAccountPage 為孿生頁——同一個殼與同一套密碼驗證，只差文案與呼叫的 API
 * （後端 /verify-email 與 /activate-account 亦只差接受的 KIND）。
 */
export function VerifyEmailPage() {
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
  // 密碼規則提示 / 驗證依 PWD_POLICY 動態（#77）
  const { policy, hint } = usePasswordPolicy()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const parsed = makeResetPasswordSchema(policy?.min_len, policy?.char_types).safeParse({
      new_password: newPassword,
      confirm_password: confirmPassword,
    })
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return

    setSubmitting(true)
    try {
      await authApi.verifyEmail({ token, ...parsed.data })
      setDone(true)
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
        background: AUTH_BG_GRADIENT,
      }}
    >
      <Card sx={{ width: 440, maxWidth: "100%", p: 4 }}>
        <Typography variant="h6" gutterBottom>
          設定密碼以完成註冊
        </Typography>
        {done ? (
          <Stack spacing={2}>
            <Alert severity="success">帳號已啟用，請以新密碼登入</Alert>
            <Link href="/" underline="hover">
              前往登入
            </Link>
          </Stack>
        ) : token === "" ? (
          <Stack spacing={2}>
            <Alert severity="error">驗證連結無效</Alert>
            <Typography variant="body2" color="text.secondary">
              連結可能已失效或逾時，請回登入頁重新註冊或重寄驗證信。
            </Typography>
            <Link href="/" underline="hover">
              回登入頁
            </Link>
          </Stack>
        ) : (
          <form onSubmit={handleSubmit}>
            <Stack spacing={2}>
              {apiError !== null && <Alert severity="error">{apiError}</Alert>}
              <Typography variant="body2" color="text.secondary">
                Email 已驗證，設定密碼即可啟用帳號並登入。
              </Typography>
              <TextField
                label="設定密碼"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                error={"new_password" in fieldErrors}
                helperText={fieldErrors.new_password ?? hint}
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
