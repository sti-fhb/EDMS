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

/** 頂列：系統標題 + 右上個資選單（個人資料 / 登出）。 */
export function AppHeader() {
  const { setToken } = useAuth()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)

  const handleLogout = () => {
    setAnchorEl(null)
    // 骨架：僅清除前端 token；實際登出稽核（LOGOUT）屬 US1
    setToken(null)
  }

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
          EDMS 平台後台
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
