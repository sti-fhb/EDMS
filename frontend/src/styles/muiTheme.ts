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
     * 表頭樣式（#828 底色、#832 不折行）。**設在 theme 而非逐頁寫**——全站 26 張表裡
     * 只有 7 張走共用的 `AppTable`，另外 19 張是各頁手拼的 MUI `Table`；改 `AppTable`
     * 涵蓋不到後者，逐頁補則要動 13 個不相干的檔，且每新增一張表都得再記得加一次。
     *
     * 📌 #828 原寫「21 張表 / B 組 14 張」為加總錯誤，#832 重數後更正為 26 / 19。
     *
     * ## 底色：直接寫 `#f8f9fa`，不取 `grey.50`
     *
     * `#f8f9fa` 是 wireframe（`docs/wireframes/{dm,dp,et}/index.html` 的
     * `table.wf-table th`）與 `ui-design-guide` 的規範值，換成相近的內建 token
     * （#fafafa）會讓文件、設計稿與實作三者對不起來，而 0.4% 的色差看不出來、
     * 沒有人會發現是哪裡偏掉的。
     *
     * ⛔ 元件裡不要再寫 `sx={{ "& th": { bgcolor: ... } }}`——`sti-ui-design.md`
     * 禁止硬編碼色碼的對象是元件，theme 本來就是色值的定義處（palette 已有 #1b5e20 等）。
     *
     * ## `nowrap`：桌機寬度下是 no-op，只在窄螢幕才有差
     *
     * #832 逐張查過：26 張表的表頭字串最長 5 字（「廢止申請人」），在各自的欄寬下
     * **本來就不會折行**，所以桌機看不出變化；它擋的是日後新增長表頭時列高跳動。
     *
     * ⚠️ 已知取捨：7 張表用 `tableLayout: "fixed"`，窄螢幕下其表頭改為溢出而非折行。
     * 刻意不加 `textOverflow: "ellipsis"`——截斷會**藏掉字**，而折行至少看得到全文；
     * wireframe 的 `table.wf-table th` 也只有 `nowrap`、沒有 ellipsis。那些表在手機
     * 寬度本來就難用（7 欄塞進 375px），真正的解是補捲動容器，見 `ui-design-guide` §4。
     */
    MuiTableCell: {
      styleOverrides: {
        head: { backgroundColor: "#f8f9fa", whiteSpace: "nowrap" },
      },
    },
    /**
     * 內容列 hover 高亮（#832）。
     *
     * ## 為什麼設在 theme 而不是逐表加 `hover` prop
     *
     * 盤點時 26 張表的分布是：可點的 6 張全有 hover（一致），但**不可點的 20 張裡
     * 9 張有、11 張沒有**——等於沒有規則。2026-10-27 裁示「全部補齊、26 張一致」，
     * 並定調 hover 的語意是**「游標在這一列」**（幫助寬表橫向追行），**不是**「這一列
     * 可以點」。可點與否另由 `cursor: "pointer"` 與 `onClick` 表達。
     *
     * 設在這裡，新增的表格自動一致；逐表加 prop 則是下一張新表又會忘記。
     *
     * ⚠️ 既有的 15 處 `<TableRow hover>` 因此成為**冗餘但無害**（同色、冪等）。刻意
     * 不在本次一併移除：那要動 13 個不相干的檔，而留著不會造成任何行為差異。
     * ⛔ 新寫的表格**不需要**再加 `hover` prop。
     *
     * ## ⚠️ 選擇器刻意保持最低 specificity
     *
     * 不寫成 `&:not(.MuiTableRow-head):not(.MuiTableRow-footer):hover`——那是 (0,4,0)，
     * 會**高到呼叫端的 `sx` 蓋不過**（`sx` 產生的單一 class ＋ `:hover` 只有 (0,2,0)）。
     * 實際踩過：`AppTable` 的佔位列想退回 hover 卻無效，而畫面上看不出是被誰蓋住。
     *
     * 不必排除表頭：`th` 自己帶不透明的 `#f8f9fa`（見上方 `MuiTableCell.head`），
     * 會把列的 hover 色整個蓋住。表尾全站未使用（無 `TableFooter`）。
     */
    MuiTableRow: {
      styleOverrides: {
        root: ({ theme }) => ({
          "&:hover": { backgroundColor: theme.palette.action.hover },
        }),
      },
    },
  },
})
