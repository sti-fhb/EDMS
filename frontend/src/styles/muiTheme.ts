import { createTheme } from "@mui/material/styles"

// EDMS 平台主題（配色對齊 wireframe：深綠主色）。
export const muiTheme = createTheme({
  palette: {
    primary: { main: "#1b5e20", dark: "#003300", light: "#4c8c4a" },
    background: { default: "#f5f0e6" },
  },
  typography: {
    fontFamily: ['"Noto Sans TC"', "system-ui", "Arial", "sans-serif"].join(","),
  },
})
