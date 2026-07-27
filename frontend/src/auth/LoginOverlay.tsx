import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Link from "@mui/material/Link"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { FormEvent } from "react"

import { ForgotPasswordForm } from "./ForgotPasswordForm"
import { RegisterForm } from "./RegisterForm"
import { authApi } from "./authService"
import { useAuth } from "./useAuth"
import { useCooldown, formatCountdown } from "../hooks/useCooldown"
import { toApiError } from "../services/http"

/**
 * 登入 overlay（全畫面遮罩）：登入 / 註冊分頁。
 * 登入：帳密 + 錯誤提示（後端 error_message）；查無帳號可切註冊、未驗證（DP_AUTH_010）可重寄驗證信。
 * 註冊（US2 #56）：RegisterForm，送出後於分頁內顯示「驗證信已寄」（不跳登入，需驗證後才能登入）。
 */
export function LoginOverlay() {
  const { login, sessionExpired } = useAuth()
  const [tab, setTab] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [resendNote, setResendNote] = useState<string | null>(null)
  const [forgotMode, setForgotMode] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const resendCooldown = useCooldown()
  // 冷卻僅對「起算時的那個 Email」生效——換 Email 後不被前一個 Email 的冷卻誤擋
  const resendCoolingDown = resendCooldown.active && resendCooldown.key === email

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorCode(null)
    setErrorMessage(null)
    setResendNote(null)
    setSubmitting(true)
    try {
      await login(email, password)
    } catch (err) {
      const apiError = toApiError(err)
      setErrorCode(apiError.errorCode)
      setErrorMessage(apiError.errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  const handleResendVerification = async () => {
    if (resendCoolingDown) return
    setResendNote(null)
    try {
      const retryAfter = await authApi.resendVerification(email)
      setResendNote("若該 Email 有待驗證的註冊，已重新寄出驗證信，請至信箱查收")
      if (retryAfter) resendCooldown.start(retryAfter, email)
    } catch (err) {
      const apiError = toApiError(err)
      setResendNote(apiError.errorMessage)
      // 冷卻中（429）→ 依 retry_after 起算倒數（綁定此 Email），避免使用者繼續狂點
      if (apiError.retryAfter) resendCooldown.start(apiError.retryAfter, email)
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
      <Card sx={{ width: 400, maxWidth: "100%", p: 4, position: "relative" }}>
        <Typography variant="h6" align="center" gutterBottom>
          EDMS
        </Typography>
        {forgotMode ? (
          <ForgotPasswordForm onBack={() => setForgotMode(false)} />
        ) : (
          <>
            <Tabs
              value={tab}
              onChange={(_e, v) => {
                setTab(v as "login" | "register")
                setErrorMessage(null)
                setResendNote(null)
              }}
              variant="fullWidth"
              sx={{ mb: 2 }}
            >
              <Tab value="login" label="登入" />
              <Tab value="register" label="註冊" />
            </Tabs>

            {tab === "login" ? (
              <>
                {sessionExpired && errorMessage === null && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    閒置逾時已自動登出，請重新登入
                  </Alert>
                )}
                {resendNote !== null && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    {resendNote}
                  </Alert>
                )}
                {errorMessage !== null && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {errorMessage}
                    {errorCode === "DP_AUTH_007" && (
                      <Box component="span" sx={{ ml: 1 }}>
                        <Link component="button" type="button" underline="hover" onClick={() => setTab("register")}>
                          前往註冊
                        </Link>
                      </Box>
                    )}
                    {errorCode === "DP_AUTH_010" && (
                      <Box component="span" sx={{ ml: 1 }}>
                        <Link
                          component="button"
                          type="button"
                          underline="hover"
                          disabled={resendCoolingDown}
                          sx={{ opacity: resendCoolingDown ? 0.5 : 1, pointerEvents: resendCoolingDown ? "none" : "auto" }}
                          onClick={handleResendVerification}
                        >
                          {resendCoolingDown
                            ? `重寄驗證信（${formatCountdown(resendCooldown.remaining)} 後）`
                            : "重寄驗證信"}
                        </Link>
                      </Box>
                    )}
                  </Alert>
                )}
                <form onSubmit={handleSubmit}>
                  <Stack spacing={2}>
                    <TextField
                      label="帳號（Email）"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      fullWidth
                      autoComplete="username"
                    />
                    <TextField
                      label="密碼"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      fullWidth
                      autoComplete="current-password"
                    />
                    <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
                      登入
                    </Button>
                    <Link
                      component="button"
                      type="button"
                      underline="hover"
                      variant="body2"
                      onClick={() => {
                        setForgotMode(true)
                        setErrorMessage(null)
                        setResendNote(null)
                      }}
                    >
                      忘記密碼？
                    </Link>
                  </Stack>
                </form>
              </>
            ) : (
              <RegisterForm />
            )}
          </>
        )}
      </Card>
    </Box>
  )
}
