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

/**
 * 登入 overlay 骨架（全畫面遮罩）。
 * 僅 UI 殼：email + 密碼 + 忘記密碼連結。實際登入 / JWT / redirect 屬 US1 + T013/T014，
 * 目前送出僅以假 token 進入後台供骨架瀏覽。
 */
export function LoginOverlay() {
  const { setToken } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    // TODO(US1/T013): 呼叫登入 API 取得 JWT；此處為骨架佔位。
    setToken("dev-skeleton-token")
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
            <Button type="submit" variant="contained" size="large" fullWidth>
              登入
            </Button>
            <Link href="#" underline="hover" variant="body2">
              忘記密碼？
            </Link>
          </Stack>
        </form>
      </Card>
    </Box>
  )
}
