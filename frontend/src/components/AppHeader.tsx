import AccountCircle from "@mui/icons-material/AccountCircle"
import AppBar from "@mui/material/AppBar"
import Box from "@mui/material/Box"
import IconButton from "@mui/material/IconButton"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import Toolbar from "@mui/material/Toolbar"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { useAuth } from "../auth/useAuth"

/** 頂列：系統標題 + 右上個資選單（個人資料 / 登出）。title 預設為後台語意，入口頁等情境可覆寫。 */
export function AppHeader({ title = "EDMS 平台後台" }: { title?: string }) {
  const { logout } = useAuth()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)

  const handleLogout = () => {
    setAnchorEl(null)
    // 呼叫登出：寫 LOGOUT 稽核並清除 memory-only token（US1）
    void logout()
  }

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
          {title}
        </Typography>
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
            <MenuItem onClick={() => setAnchorEl(null)}>個人資料</MenuItem>
            <MenuItem onClick={handleLogout}>登出</MenuItem>
          </Menu>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
