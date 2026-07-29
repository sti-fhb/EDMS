import Box from "@mui/material/Box"
import Drawer from "@mui/material/Drawer"
import Toolbar from "@mui/material/Toolbar"
import { Outlet } from "react-router-dom"

import { AppHeader } from "../components/AppHeader"
import { Sidebar } from "../components/Sidebar"

const DRAWER_WIDTH = 220

/**
 * 統一 App Shell（#89 導覽重構）：全域頂列 + 常駐側欄 + 主內容。
 * 取代原分離的 PortalLayout（無側欄卡片頁）與 DpLayout（後台側欄）——登入後各頁（歡迎頁 /
 * 個人資料 / DP 後台）共用同一 shell、側欄常駐，解決跨區導覽割裂（如個資頁返回不回原側欄）。
 */
export function AppShell() {
  return (
    <Box sx={{ display: "flex" }}>
      <AppHeader title="EDMS 教育訓練文件管理系統" />
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
