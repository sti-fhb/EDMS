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
import { Link as RouterLink, useSearchParams } from "react-router-dom"

import { AUTH_BG_GRADIENT } from "./authBackground"
import { authApi } from "./authService"
import { makeResetPasswordSchema } from "./schemas/resetPasswordSchema"
import { usePasswordPolicy } from "../hooks/usePasswordPolicy"
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
  // 密碼規則提示 / 驗證依 PWD_POLICY 動態（#77）；`status` 讓失效連結於**點連結時**即可判定（#673）
  const { policy, hint, status } = usePasswordPolicy({ kind: "reset", token })

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
      await authApi.resetPassword({ token, ...parsed.data })
      setDone(true)
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", p: 2, background: AUTH_BG_GRADIENT }}>
      <Card sx={{ width: 440, maxWidth: "100%", p: 4 }}>
        <Typography variant="h6" gutterBottom>
          重設密碼
        </Typography>
        {done ? (
          <Stack spacing={2}>
            <Alert severity="success">密碼已更新，請以新密碼登入</Alert>
            {/* 經 router 才會帶上部署 base path；`href="/"` 會跳到網域根目錄（同 origin 的另一套系統，#607） */}
            <Link component={RouterLink} to="/" underline="hover">
              返回登入
            </Link>
          </Stack>
        ) : token === "" ? (
          // 網址根本沒帶 token——與「連結失效」是不同情況，訊息分開
          <Alert severity="error">連結無效，請重新申請忘記密碼</Alert>
        ) : status === "token-invalid" ? (
          // 連結查無 / 已用 / 逾期（#673）。spec_us3 AC 3 要求於**點連結時**即拒絕——
          // 原本會照常渲染表單，使用者得照著錯的門檻打完一組密碼、按下送出才被擋。
          // ⚠️ 只有 `token-invalid` 走這裡；`unavailable`（限流 / 連線異常）**不得**說連結失效。
          <Alert severity="error">連結已失效，請重新申請</Alert>
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
                重設密碼
              </Button>
            </Stack>
          </form>
        )}
      </Card>
    </Box>
  )
}
