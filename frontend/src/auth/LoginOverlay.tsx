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

import { RegisterForm } from "./RegisterForm"
import { useAuth } from "./useAuth"
import { toApiError } from "../services/http"

/**
 * 登入 overlay（全畫面遮罩）：登入 / 註冊分頁。
 * 登入：帳密 + 錯誤提示（後端 error_message，對齊 DP-MSG-LOGIN）+ 逾時重登提示；查無帳號可切註冊分頁。
 * 註冊（US2）：RegisterForm，成功後跳回登入分頁並預填 Email。成功登入由 AuthProvider 撤除 overlay。
 */
export function LoginOverlay() {
  const { login, sessionExpired } = useAuth()
  const [tab, setTab] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [registeredMessage, setRegisteredMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setErrorCode(null)
    setErrorMessage(null)
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

  const handleRegistered = (registeredEmail: string) => {
    setTab("login")
    setEmail(registeredEmail)
    setErrorCode(null)
    setErrorMessage(null)
    setRegisteredMessage("註冊成功，請以新帳號登入")
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
        <Tabs
          value={tab}
          onChange={(_e, v) => {
            setTab(v as "login" | "register")
            setErrorMessage(null)
            setRegisteredMessage(null)
          }}
          variant="fullWidth"
          sx={{ mb: 2 }}
        >
          <Tab value="login" label="登入" />
          <Tab value="register" label="註冊" />
        </Tabs>

        {tab === "login" ? (
          <>
            {registeredMessage !== null && (
              <Alert severity="success" sx={{ mb: 2 }}>
                {registeredMessage}
              </Alert>
            )}
            {sessionExpired && errorMessage === null && registeredMessage === null && (
              <Alert severity="info" sx={{ mb: 2 }}>
                閒置逾時已自動登出，請重新登入
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
                <Link href="/forgot-password" underline="hover" variant="body2">
                  忘記密碼？
                </Link>
              </Stack>
            </form>
          </>
        ) : (
          <RegisterForm onSuccess={handleRegistered} />
        )}
      </Card>
    </Box>
  )
}
