import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import type { FormEvent } from "react"

import { authApi } from "./authService"
import { RegisterRequestSchema } from "./schemas/registerSchema"
import { toApiError } from "../services/http"
import { getFieldErrors } from "../utils/zodUtils"

/**
 * 自助註冊表單（US2，登入 overlay 的「註冊」分頁）。
 * 前端 Zod 驗證（Email 格式 / 必填 / 複雜度 / 兩次一致）→ 後端伺服器端權威檢核；
 * 成功後由父層跳回登入分頁並預填 Email。錯誤訊息直接採後端 error_message（對齊 DP-MSG-REGISTER）。
 */
export function RegisterForm({ onSuccess }: { onSuccess: (email: string) => void }) {
  const [email, setEmail] = useState("")
  const [userName, setUserName] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setApiError(null)
    const values = { email, user_name: userName, password, confirm_password: confirmPassword }
    const parsed = RegisterRequestSchema.safeParse(values)
    setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
    if (!parsed.success) return

    setSubmitting(true)
    try {
      await authApi.register(parsed.data)
      onSuccess(email)
    } catch (err) {
      setApiError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
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
        <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
          建立帳號
        </Button>
        <Typography variant="caption" color="text.secondary">
          註冊成功即可登入（自助註冊即用），自動取得 ET 學員預設角色；其他角色由管理者於權限管理開通。
        </Typography>
      </Stack>
    </form>
  )
}
