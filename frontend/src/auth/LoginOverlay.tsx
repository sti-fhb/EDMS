import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Link from "@mui/material/Link"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { FormEvent } from "react"

import { useAuth } from "./useAuth"
import { toApiError } from "../services/http"

/**
 * 登入 overlay（全畫面遮罩）：帳密登入 + 錯誤提示 + 逾時重登提示。
 * 錯誤訊息直接採後端 error_message（已對齊 spec 訊息表 DP-MSG-LOGIN-001~007）；
 * 查無帳號（DP_AUTH_007）額外提供註冊入口。成功後由 AuthProvider 更新狀態、overlay 自動撤除。
 */
export function LoginOverlay() {
  const { login, sessionExpired } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
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
          EDMS 登入
        </Typography>
        {sessionExpired && errorMessage === null && (
          <Alert severity="info" sx={{ mb: 2 }}>
            閒置逾時已自動登出，請重新登入
          </Alert>
        )}
        {errorMessage !== null && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {errorMessage}
            {errorCode === "DP_AUTH_007" && (
              <Box component="span" sx={{ ml: 1 }}>
                <Link href="/register" underline="hover">
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
      </Card>
    </Box>
  )
}
