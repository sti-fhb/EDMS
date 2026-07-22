import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { authApi } from "./authService"
import { toApiError } from "../services/http"

type Status = "verifying" | "success" | "error"

/**
 * 註冊驗證落點頁（US2 #56）。獨立公開頁（不套登入 overlay）：讀網址 token → 呼叫 /verify-email，
 * 成功導登入；連結無效 / 逾時顯示錯誤並引導回登入頁重新註冊 / 重寄。
 */
export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get("token")
  // 缺 token 者初始即為錯誤（不在 effect 內同步 setState，避免 react-hooks/set-state-in-effect）
  const hasToken = token !== null && token !== ""
  const [status, setStatus] = useState<Status>(hasToken ? "verifying" : "error")
  const [errorMessage, setErrorMessage] = useState<string | null>(hasToken ? null : "驗證連結無效")

  useEffect(() => {
    if (!hasToken) return // 無 token：初始 state 已為 error，不呼叫 API
    let cancelled = false
    authApi
      .verifyEmail(token)
      .then(() => {
        if (!cancelled) setStatus("success")
      })
      .catch((err) => {
        if (!cancelled) {
          setStatus("error")
          setErrorMessage(toApiError(err).errorMessage)
        }
      })
    return () => {
      cancelled = true
    }
  }, [token, hasToken])

  return (
    <Box
      sx={{
        position: "fixed",
        inset: 0,
        bgcolor: "background.default",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
      }}
    >
      <Card sx={{ width: 400, maxWidth: "100%", p: 4, textAlign: "center" }}>
        <Typography variant="h6" gutterBottom>
          EDMS 帳號驗證
        </Typography>
        {status === "verifying" && (
          <Stack spacing={2} alignItems="center" sx={{ py: 2 }}>
            <CircularProgress aria-label="驗證中" />
            <Typography variant="body2" color="text.secondary">
              驗證中，請稍候…
            </Typography>
          </Stack>
        )}
        {status === "success" && (
          <Stack spacing={2}>
            <Alert severity="success">帳號已啟用，請以新帳號登入。</Alert>
            <Button variant="contained" onClick={() => navigate("/")}>
              前往登入
            </Button>
          </Stack>
        )}
        {status === "error" && (
          <Stack spacing={2}>
            <Alert severity="error">{errorMessage ?? "驗證連結無效"}</Alert>
            <Typography variant="body2" color="text.secondary">
              連結可能已失效或逾時，請回登入頁重新註冊或重寄驗證信。
            </Typography>
            <Button variant="outlined" onClick={() => navigate("/")}>
              回登入頁
            </Button>
          </Stack>
        )}
      </Card>
    </Box>
  )
}
