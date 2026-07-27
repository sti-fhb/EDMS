/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
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
