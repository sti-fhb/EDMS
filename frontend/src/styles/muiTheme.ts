import { createTheme } from "@mui/material/styles"

// EDMS 平台主題（配色對齊 wireframe：深綠主色；字體大小 / 介面背景 / 文字 / 分隔線對齊 TBMS 母專案）。
export const muiTheme = createTheme({
  palette: {
    primary: { main: "#1b5e20", dark: "#003300", light: "#4c8c4a" },
    // 對齊 TBMS：內容區 #f5f5f5、卡片 / 側欄 #ffffff、文字 #333/#999、分隔線 #dee2e6
    background: { default: "#f5f5f5", paper: "#ffffff" },
    text: { primary: "#333333", secondary: "#999999" },
    divider: "#dee2e6",
  },
  typography: {
    fontFamily: ['"Noto Sans TC"', "system-ui", "Arial", "sans-serif"].join(","),
    // 對齊 TBMS 基準字級 14px（MUI 以此換算 rem）
    fontSize: 14,
  },
  shape: { borderRadius: 6 },
})
