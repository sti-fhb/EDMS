import Box from "@mui/material/Box"
import Drawer from "@mui/material/Drawer"
import Toolbar from "@mui/material/Toolbar"
import { Outlet } from "react-router-dom"

import { AppHeader } from "../components/AppHeader"
import { Sidebar } from "../components/Sidebar"

const DRAWER_WIDTH = 220

/** DP 後台 layout：頂列 + 左側 sidebar + 主內容 Outlet。 */
export function DpLayout() {
  return (
    <Box sx={{ display: "flex" }}>
      <AppHeader />
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
      >
        <Toolbar />
        <Sidebar />
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  )
}
