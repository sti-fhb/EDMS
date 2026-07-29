import Container from "@mui/material/Container"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { authApi } from "../auth/authService"
import { useAuth } from "../auth/useAuth"
import { profileApi } from "../dp/user/profileService"

const TAGLINE = "教育訓練與文件管理系統"

/**
 * 中性歡迎頁（#89 P1）：登入後主頁，不綁任何模組權限、永遠存在。
 * 顯示問候（帶姓名）+ 系統定位 + 版本號。姓名 / 版本載入失敗時靜默保底（問候退回「歡迎」、
 * 版本行隱藏），不阻斷頁面。P2+ 再於此依權限疊加管理者概況 / ET / DM 儀表板。
 */
export function WelcomePage() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  // 本頁為 index 路由、未登入時亦已掛載（被 LoginOverlay 覆蓋）；enabled 僅在已登入且非強制變更
  // 密碼時才發查詢，避免無謂 401（比照 #41 的取捨）。
  const enabled = isAuthenticated && !mustChangePwd
  const { data: me } = useQuery({ queryKey: ["profile", "me"], queryFn: profileApi.getMe, enabled })
  const { data: version } = useQuery({ queryKey: ["app", "version"], queryFn: authApi.version, enabled })

  const greeting = me?.user_name ? `歡迎，${me.user_name}` : "歡迎"

  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      <Typography variant="h4" gutterBottom>
        {greeting}
      </Typography>
      <Typography variant="body1" color="text.secondary">
        {TAGLINE}
      </Typography>
      {version !== undefined && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 3 }}>
          版本 {version}
        </Typography>
      )}
    </Container>
  )
}
