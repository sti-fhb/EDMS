import AccountCircle from "@mui/icons-material/AccountCircle"
import MenuIcon from "@mui/icons-material/Menu"
import AppBar from "@mui/material/AppBar"
import Box from "@mui/material/Box"
import ButtonBase from "@mui/material/ButtonBase"
import IconButton from "@mui/material/IconButton"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import Toolbar from "@mui/material/Toolbar"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { useAuth } from "../auth/useAuth"

/**
 * 頂列：（可選）側欄切換鈕 + 系統標題 + 右上個資選單（個人資料 / 登出）。
 * `onMenuClick` 有值時於左上顯示三條線 icon，供收合 / 展開側欄（對齊 TBMS）。
 */
export function AppHeader({ title = "EDMS 平台後台", onMenuClick }: { title?: string; onMenuClick?: () => void }) {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)

  const handleProfile = () => {
    setAnchorEl(null)
    navigate("/profile")
  }

  const handleLogout = () => {
    setAnchorEl(null)
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
        <Box>
          <IconButton
            size="large"
            aria-label="個資選單"
            aria-controls={open ? "profile-menu" : undefined}
            aria-haspopup="true"
            onClick={(e) => setAnchorEl(e.currentTarget)}
            color="inherit"
          >
            <AccountCircle />
          </IconButton>
          <Menu
            id="profile-menu"
            anchorEl={anchorEl}
            open={open}
            onClose={() => setAnchorEl(null)}
          >
            <MenuItem onClick={handleProfile}>個人資料</MenuItem>
            <MenuItem onClick={handleLogout}>登出</MenuItem>
          </Menu>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
