import AccountCircle from "@mui/icons-material/AccountCircle"
import MenuIcon from "@mui/icons-material/Menu"
import AppBar from "@mui/material/AppBar"
import Button from "@mui/material/Button"
import ButtonBase from "@mui/material/ButtonBase"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import Toolbar from "@mui/material/Toolbar"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { useAuth } from "../auth/useAuth"
import { PROFILE_ME_QUERY_KEY, profileApi } from "../dp/user/profileService"

/**
 * 頂列：（可選）側欄切換鈕 + 系統標題 + 右上使用者區（姓名 + 登出）。
 * `onMenuClick` 有值時於左上顯示三條線 icon，供收合 / 展開側欄（對齊 TBMS）。
 *
 * 使用者區對齊 TBMS（#421）：姓名與登出並排，不收在下拉選單裡。兩處刻意與 TBMS 不同——
 * TBMS 顯示的是**帳號**且不可點擊，EDMS 顯示**姓名**且點擊導向個人資料維護（DP04）。
 */
export function AppHeader({
  title = "教育訓練文件管理系統",
  onMenuClick,
}: {
  title?: string
  onMenuClick?: () => void
}) {
  const { logout, isAuthenticated, mustChangePwd } = useAuth()
  const navigate = useNavigate()

  // 兩個條件的性質不同，別只看前半：
  // - `!mustChangePwd` 是**現役**條件——`RootLayout` 之強制變更密碼頁殼與 `Outlet` 同時掛載
  //   （`{mustChangePwd && <ForceChangePasswordShell />}`），故未完成變更時本元件確實在頁殼背後
  //   渲染。⚠️ `/dp/user/me` **刻意不套密碼閘**（US8 逃生門，見 `dp/user/router.py` §個人資料維護），
  //   打了會回 200 而非 403；擋它的理由是**不在使用者完成強制變更前就把個資拉進 query cache**，
  //   而非「會被擋下」。
  // - `isAuthenticated` 為**防禦性**——現行 `RootLayout` 未登入時直接回 `<LoginOverlay />`、
  //   不渲染 `Outlet`，故實際不會觸發；保留是為了獨立渲染本元件的測試情境，以及避免日後
  //   掛載時機又改回「先渲染再覆蓋」時重蹈 401 且不重抓的覆轍。
  // 比照 WelcomePage 的同款守衛。
  const { data: me } = useQuery({
    queryKey: PROFILE_ME_QUERY_KEY,
    queryFn: profileApi.getMe,
    enabled: isAuthenticated && !mustChangePwd,
  })

  // 送出中旗標：`logout()` 要等後端來回才會清 token，期間按鈕仍在畫面上且可再點。
  // 舊版是下拉選單的 MenuItem——關閉動畫期間點擊被 backdrop 吃掉，等於有隱性 debounce；
  // 改為獨立按鈕後那層沒了，快速雙擊會寫出**兩筆 LOGOUT 稽核**（後端每次呼叫都記一筆）。
  const [loggingOut, setLoggingOut] = useState(false)

  const handleLogout = () => {
    if (loggingOut) return
    setLoggingOut(true)
    // 呼叫登出：寫 LOGOUT 稽核並清除 memory-only token（US1）
    void logout()
    // 導回主頁（/ ＝中性歡迎頁）：手動登出時避免停在 /profile 等深層路由，重新登入後被留在該頁。
    // idle-timeout 自動登出不走此路徑、保留原頁（US1 意圖）。
    navigate("/")
  }

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        {onMenuClick && (
          <IconButton edge="start" color="inherit" aria-label="切換側欄" onClick={onMenuClick} sx={{ mr: 1 }}>
            <MenuIcon />
          </IconButton>
        )}
        <ButtonBase
          onClick={() => navigate("/")}
          aria-label="回主頁"
          sx={{ flexGrow: 1, justifyContent: "flex-start", color: "inherit" }}
        >
          <Typography variant="h6" component="div">
            {title}
          </Typography>
        </ButtonBase>
        <Stack direction="row" alignItems="center" spacing={1}>
          {/* 姓名未載入時整區不渲染：避免先出現空按鈕再跳出文字 */}
          {me?.user_name && (
            <ButtonBase
              onClick={() => navigate("/profile")}
              sx={{ color: "inherit", borderRadius: 1, px: 0.5, py: 0.25, gap: 0.5 }}
            >
              <AccountCircle sx={{ fontSize: 16, opacity: 0.85 }} />
              <Typography variant="body2" sx={{ opacity: 0.9, fontSize: "0.82rem" }}>
                {me.user_name}
              </Typography>
            </ButtonBase>
          )}
          <Button
            color="inherit"
            size="small"
            onClick={handleLogout}
            disabled={loggingOut}
            sx={{ opacity: 0.85, fontSize: "0.82rem", minWidth: "auto" }}
          >
            登出
          </Button>
        </Stack>
      </Toolbar>
    </AppBar>
  )
}
