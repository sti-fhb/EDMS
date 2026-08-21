import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { authApi } from "../auth/authService"
import { useAuth } from "../auth/useAuth"
import { DmOverviewWidget } from "../dm/dashboard/DmOverviewWidget"
import { PROFILE_ME_QUERY_KEY, profileApi } from "../dp/user/profileService"
import { useModuleSummary } from "../layouts/useModuleSummary"

const TAGLINE = "教育訓練與文件管理系統"

/**
 * 中性歡迎頁（#89 P1）：登入後主頁，不綁任何模組權限、永遠存在。
 * 顯示問候（帶姓名）+ 系統定位 + 版本號。姓名 / 版本載入失敗時靜默保底（問候退回「歡迎」、
 * 版本行隱藏），不阻斷頁面。**具任一 DM 角色者於此依權限疊加「DM 文件概況」widget（US7 / #89）**，
 * 無 DM 角色者不顯示（最小知悉）。
 */
export function WelcomePage() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  // 本頁為 index 路由、未登入時亦已掛載（被 LoginOverlay 覆蓋）；enabled 僅在已登入且非強制變更
  // 密碼時才發查詢，避免無謂 401（比照 #41 的取捨）。
  const enabled = isAuthenticated && !mustChangePwd
  const { data: me } = useQuery({ queryKey: PROFILE_ME_QUERY_KEY, queryFn: profileApi.getMe, enabled })
  const { data: version } = useQuery({ queryKey: ["app", "version"], queryFn: authApi.version, enabled })
  const { data: modules } = useModuleSummary()

  const greeting = me?.user_name ? `歡迎，${me.user_name}` : "歡迎"

  return (
    <Box sx={{ p: 3 }}>
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
      {/* US7 / #89：具任一 DM 角色者才疊加「DM 文件概況」；無 DM 角色者不顯示（最小知悉）*/}
      {enabled && modules?.dm.has_role && <DmOverviewWidget />}
    </Box>
  )
}
