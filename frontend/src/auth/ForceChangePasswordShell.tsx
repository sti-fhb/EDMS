import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { useAuth } from "./useAuth"

/**
 * 強制變更密碼頁殼（US1 §11：閘 + 導向 + 頁殼）。
 * 顯示逾效期 / 初始密碼警告（DP-MSG-LOGIN-005）與新密碼 / 確認欄位。
 * 實際變更提交端點與複雜度 / 重複性檢核屬 US8（spec_us1 Clarification）；US1 僅提供頁殼，
 * 提交按鈕於 US8 接上前不送出。提供登出以離開此狀態。
 */
export function ForceChangePasswordShell() {
  const { logout } = useAuth()
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")

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
      <Card sx={{ width: 440, maxWidth: "100%", p: 4 }}>
        <Typography variant="h6" gutterBottom>
          變更密碼
        </Typography>
        <Alert severity="warning" sx={{ mb: 2 }}>
          密碼已逾效期（或首次登入），請立即變更密碼
        </Alert>
        <Stack spacing={2}>
          <TextField
            label="新密碼"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            fullWidth
            autoComplete="new-password"
          />
          <TextField
            label="確認新密碼"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            fullWidth
            autoComplete="new-password"
          />
          {/* 提交端點屬 US8，接上前不送出 */}
          <Button variant="contained" size="large" fullWidth disabled>
            變更密碼
          </Button>
          <Typography variant="caption" color="text.secondary">
            （密碼變更提交將於 US8 完成）
          </Typography>
          <Button variant="text" onClick={() => void logout()}>
            返回登入
          </Button>
        </Stack>
      </Card>
    </Box>
  )
}
