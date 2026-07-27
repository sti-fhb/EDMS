import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useRef, useState } from "react"
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
  // 已對哪個 token 送過驗證請求；ref 在同一元件實例間保留，用於去重
  const requestedTokenRef = useRef<string | null>(null)
  // 當前是否仍掛載中（取代舊的 closure cancelled，才能讓「去重後只剩的那個請求」由最後一次掛載收斂 state）
  const activeRef = useRef(true)

  useEffect(() => {
    activeRef.current = true
    if (!hasToken) return // 無 token：初始 state 已為 error，不呼叫 API
    // StrictMode（dev）會讓掛載期 effect 跑兩次；同一 token 已送過就不再重打，
    // 避免兩個 /verify-email 並發互撞、輸的那個回 409 誤報「已被註冊」
    if (requestedTokenRef.current !== token) {
      requestedTokenRef.current = token
      authApi
        .verifyEmail(token)
        .then(() => {
          if (activeRef.current) setStatus("success")
        })
        .catch((err) => {
          if (activeRef.current) {
            setStatus("error")
            setErrorMessage(toApiError(err).errorMessage)
          }
        })
    }
    return () => {
      activeRef.current = false
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
