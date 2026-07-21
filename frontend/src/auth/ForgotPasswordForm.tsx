import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useState } from "react"
import type { FormEvent } from "react"

import { authApi } from "./authService"
import { toApiError } from "../services/http"

const FORGOT_MESSAGE = "若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設"

/**
 * 忘記密碼申請表單（US3，登入 overlay 內）。
 * 送出後一律顯示相同提示（DP-MSG-FORGOT-001，防帳號列舉）；不因帳號是否存在改變畫面。
 */
export function ForgotPasswordForm({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await authApi.forgotPassword(email)
      setDone(true)
    } catch (err) {
      setError(toApiError(err).errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  if (done) {
    return (
      <Stack spacing={2}>
        <Alert severity="info">{FORGOT_MESSAGE}</Alert>
        <Button variant="text" onClick={onBack}>
          返回登入
        </Button>
      </Stack>
    )
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack spacing={2}>
        {error !== null && <Alert severity="error">{error}</Alert>}
        <TextField
          label="帳號（Email）"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          fullWidth
          autoComplete="email"
        />
        <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
          送出
        </Button>
        <Button variant="text" onClick={onBack}>
          返回登入
        </Button>
      </Stack>
    </form>
  )
}
