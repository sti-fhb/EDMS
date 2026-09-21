/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// 站台掛載路徑。院內封閉網路只給單一 IP、單一 port，EDMS 與 TBMS 靠 URL 路徑
// 前綴區分（EDMS 走 /edms/），故交付包的 build 會傳入 VITE_BASE_PATH=/edms/。
// 預設 "/" —— GCP 雲端版與本機開發維持掛在根路徑，行為不變。
// 值必須以斜線結尾，Vite 才會正確組出靜態資源的 URL。
// 詳見 TBMS repo 的 docs/infra/onprem-path-routing.md §5.1。
const basePath = process.env.VITE_BASE_PATH || "/"

// https://vite.dev/config/
export default defineConfig({
  base: basePath,
  plugins: [react()],
  server: {
    // Port 採 5174 / 後端 8001，避免與同機 TBMS（5173 / 8000）衝突（見根 README「啟動開發環境」）
    port: 5174,
    proxy: {
      "/api": {
        // 明確走 IPv4：Windows 上 localhost 會優先解析成 IPv6 ::1，而後端 fastapi dev 綁 127.0.0.1，
        // 用 localhost 會使 proxy 連 ::1:8001 被拒（ECONNREFUSED）。指定 127.0.0.1 避免此問題。
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
})
