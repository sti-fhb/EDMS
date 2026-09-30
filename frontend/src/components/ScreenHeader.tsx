import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import type { ReactNode } from "react"

import { getScreen } from "../layouts/navItems"

interface ScreenHeaderProps {
  /** 畫面代號（如 `DP05`）：icon 與預設標題取自 `navItems`，與側欄同源。 */
  code: string
  /** 覆寫標題（僅限同一畫面有不同狀態時，如 ET05 的「新增課程」/「課程編輯」）。 */
  title?: string
  /** 標題前的元素（如返回鈕）。 */
  leading?: ReactNode
  /** 緊鄰標題的元素（如狀態 Chip）。 */
  adornment?: ReactNode
  /** 靠右的元素（操作按鈕、篩選下拉等）。 */
  actions?: ReactNode
}

/**
 * 頁面標題列（對齊 TBMS `ScreenHeader`）：icon + 功能名稱（粗體 1.3rem）＋綠色 2px 底線。
 * 三個模組所有功能頁左上一律用它，字級與位置才會一致。
 */
export function ScreenHeader({ code, title, leading, adornment, actions }: ScreenHeaderProps) {
  const { icon: Icon, label } = getScreen(code)
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 1,
        pb: 1,
        mb: 2,
        borderBottom: 2,
        borderColor: "primary.main",
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        {leading}
        <Icon color="primary" />
        <Typography component="h1" sx={{ fontWeight: 700, fontSize: "1.3rem" }}>
          {title ?? label}
        </Typography>
        {adornment}
      </Box>
      {actions}
    </Box>
  )
}
