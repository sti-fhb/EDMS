import Box from "@mui/material/Box"
import Toolbar from "@mui/material/Toolbar"
import { Outlet } from "react-router-dom"

import { AppHeader } from "../components/AppHeader"

/**
 * 入口頁殼：全域頂列（含登出）+ 主內容，**無左側側欄**。
 * 對齊 wireframe「登入後畫面共用頂列 navbar，入口頁差異僅在無側欄」（見 dp/index.html）。
 * 與 DpLayout 的差別即少了 Drawer；頂列固定定位，故以 Toolbar 佔位避免內容被蓋住。
 */
export function PortalLayout() {
  return (
    <Box>
      <AppHeader title="EDMS 教育訓練文件管理系統" />
      <Box component="main">
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  )
}