import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { FormEvent } from "react"

import { authApi } from "./authService"
import { RegisterRequestSchema } from "./schemas/registerSchema"
import { useCooldown, formatCountdown } from "../hooks/useCooldown"
import { toApiError } from "../services/http"
import { getFieldErrors } from "../utils/zodUtils"

/**
 * 自助註冊表單（US2 #56，登入 overlay 的「註冊」分頁）。
 * 前端 Zod 驗證 → 後端伺服器端權威檢核。方案 B：送出成功後**不建帳號、不跳登入**，
 * 改顯示「驗證信已寄」狀態並提供重寄；使用者需點信中連結完成驗證後才能登入。
 */
export function RegisterForm() {
  const [email, setEmail] = useState("")
  const [userName, setUserName] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // 註冊成功後記住 Email，切換為「驗證信已寄」狀態（可重寄）
  const [sentEmail, setSentEmail] = useState<string | null>(null)
  const [resendNote, setResendNote] = useState<string | null>(null)
  // 驗證信寄送冷卻（#74）：register 成功 / 重寄成功皆起算；冷卻中（429）依 retry_after 起算。
  // 冷卻綁定起算時的 Email——換 Email 後合法操作不被前一個 Email 的冷卻誤擋。
  const cooldown = useCooldown()
  const submitCoolingDown = cooldown.active && cooldown.key === email
  const resendCoolingDown = cooldown.active && cooldown.key === sentEmail

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const values = { email, user_name: userName, password, confirm_password: confirmPassword }
    const parsed = RegisterRequestSchema.safeParse(values)
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return

    setSubmitting(true)
    try {
      const retryAfter = await authApi.register(parsed.data)
      setSentEmail(email)
      if (retryAfter) cooldown.start(retryAfter, email)
    } catch (err) {
      const apiError = toApiError(err)
      setApiError(apiError.errorMessage)
      // 冷卻中重複註冊（429）→ 起算倒數（綁定此 Email）並暫時 disable 送出
      if (apiError.retryAfter) cooldown.start(apiError.retryAfter, email)
    } finally {
      setSubmitting(false)
    }
  }

  const handleResend = async () => {
    if (sentEmail === null || resendCoolingDown) return
    setResendNote(null)
    try {
      const retryAfter = await authApi.resendVerification(sentEmail)
      setResendNote("已重新寄出驗證信，請至信箱查收")
      if (retryAfter) cooldown.start(retryAfter, sentEmail)
    } catch (err) {
      const apiError = toApiError(err)
      setResendNote(apiError.errorMessage)
      if (apiError.retryAfter) cooldown.start(apiError.retryAfter, sentEmail)
    }
  }

  if (sentEmail !== null) {
    return (
      <Stack spacing={2}>
        <Alert severity="success">
          驗證信已寄至 <strong>{sentEmail}</strong>，請於 30 分鐘內點信中連結完成驗證後即可登入。
        </Alert>
        {resendNote !== null && <Alert severity="info">{resendNote}</Alert>}
        <Typography variant="body2" color="text.secondary">
          沒收到信？請檢查垃圾郵件匣，或重新寄送。
        </Typography>
        <Button variant="outlined" onClick={handleResend} disabled={resendCoolingDown}>
          {resendCoolingDown ? `重寄驗證信（${formatCountdown(cooldown.remaining)} 後）` : "重寄驗證信"}
        </Button>
      </Stack>
    )
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack spacing={2}>
        {apiError !== null && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {apiError}
          </Alert>
        )}
        <TextField
          label="帳號（Email）"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={"email" in fieldErrors}
          helperText={fieldErrors.email}
          fullWidth
          autoComplete="email"
        />
        <TextField
          label="姓名"
          value={userName}
          onChange={(e) => setUserName(e.target.value)}
          error={"user_name" in fieldErrors}
          helperText={fieldErrors.user_name}
          fullWidth
        />
        <TextField
          label="密碼"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={"password" in fieldErrors}
          helperText={fieldErrors.password ?? "至少 8 字元，含大小寫英文 / 數字 / 特殊符號至少 3 種"}
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
        <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting || submitCoolingDown}>
          {submitCoolingDown ? `建立帳號（${formatCountdown(cooldown.remaining)} 後）` : "建立帳號"}
        </Button>
        <Typography variant="caption" color="text.secondary">
          註冊後需完成 Email 驗證才能登入；驗證後自動取得 ET 學員預設角色，其他角色由管理者於權限管理開通。
        </Typography>
      </Stack>
    </form>
  )
}
