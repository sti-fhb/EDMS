import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { profileApi } from "../dp/user/profileService"
import { toApiError } from "../services/http"

type Status = "verifying" | "success" | "error"

/**
 * Email 變更驗證落點頁（US8，信中連結落點 /verify-email-change?token=xxx）。
 * 獨立公開頁（不套登入 overlay，置於 RootLayout 外）：讀網址 token → 呼叫 /verify-email-change，
 * 成功切換 Email 並導登入；連結無效 / 逾時顯示 PROFILE-008 並引導回登入。
 * 去重 / 掛載收斂沿用 VerifyEmailPage（StrictMode 下不重打）。
 */
export function VerifyEmailChangePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get("token")
  const hasToken = token !== null && token !== ""
  const [status, setStatus] = useState<Status>(hasToken ? "verifying" : "error")
  const [errorMessage, setErrorMessage] = useState<string | null>(hasToken ? null : "驗證連結無效")
  const requestedTokenRef = useRef<string | null>(null)
  const activeRef = useRef(true)

  useEffect(() => {
    activeRef.current = true
    if (!hasToken) return
    if (requestedTokenRef.current !== token) {
      requestedTokenRef.current = token
      profileApi
        .verifyEmailChange(token)
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
          帳號（Email）變更驗證
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
            <Alert severity="success">Email 已變更，請以新 Email 登入。</Alert>
            <Button variant="contained" onClick={() => navigate("/")}>
              前往登入
            </Button>
          </Stack>
        )}
        {status === "error" && (
          <Stack spacing={2}>
            <Alert severity="error">{errorMessage ?? "驗證連結無效"}</Alert>
            <Typography variant="body2" color="text.secondary">
              連結可能已失效或逾時，Email 變更已作廢、原 Email 維持有效；可於個人資料頁重新申請。
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
