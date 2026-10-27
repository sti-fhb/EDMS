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
  components: {
    /**
     * 表頭灰底（#828）。**設在 theme 而非逐頁寫**——全站 21 張表裡只有 7 張走共用的
     * `AppTable`，另外 14 張是各頁手拼的 MUI `Table`；改 `AppTable` 涵蓋不到後者，
     * 逐頁補則要動 13 個不相干的檔，且每新增一張表都得再記得加一次。
     *
     * 色值直接寫在此處而非取 `grey.50`（#fafafa）：`#f8f9fa` 是 wireframe
     * （`docs/wireframes/{dm,dp,et}/index.html` 的 `table.wf-table th`）與
     * `ui-design-guide` 的規範值，換成相近的內建 token 會讓文件、設計稿與實作三者
     * 對不起來，而 0.4% 的色差看不出來、沒有人會發現是哪裡偏掉的。
     *
     * ⛔ 元件裡不要再寫 `sx={{ "& th": { bgcolor: ... } }}`——`sti-ui-design.md`
     * 禁止硬編碼色碼的對象是元件，theme 本來就是色值的定義處（palette 已有 #1b5e20 等）。
     */
    MuiTableCell: {
      styleOverrides: {
        head: { backgroundColor: "#f8f9fa" },
      },
    },
  },
})
