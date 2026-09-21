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
    // ⚠️ 不要拿掉這個上限，也不要改成依核心數推算（`availableParallelism()` 之類）。
    //
    // vitest 預設依核心數開 worker，而**一個 worker 不等於一顆 CPU 的工作量**：每支測試
    // 檔都要獨立建一次 jsdom、啟一次 MSW server、把整個 React/MUI 模組圖重新解析與 JIT。
    // 12 個同時做這些事會互相搶 CPU 與記憶體頻寬，而 `testTimeout` 算的是**牆鐘**——於是
    // 本來 200ms 就過的測試因為排不到 CPU 而超時。**症狀是超時，病因是飢餓。**
    //
    // 2026-09-18（#376）實測，74 支測試檔、12 邏輯核心：
    //
    // | worker | 結果 | 牆鐘 | environment | 比值 |
    // |---|---|---|---|---|
    // | 預設 ~12 | **19 檔紅 / 35 條紅** | 487s | 2199s | 4.51× |
    // | **4** | **74/74、767/767 全綠** | 500s | 863s | 1.72× |
    //
    // 牆鐘**持平**（+2.7%），換到的是可靠性而非速度——不要期待變快。
    //
    // 🔴 平行度越高越糟，這點反直覺：在此之前 GitHub CI（4 vCPU）用同一份設定與指令一直
    // 是綠的，紅的只有核心數更多的開發機。看到「CI 綠、本機紅」時容易誤判為本機環境髒了。
    //
    // ⛔ 不往上調到 6 或 8：4 已同時滿足全綠與牆鐘持平，再往上只會更接近飢餓的懸崖，而
    // 這套測試還在長大。為省數十秒把設定放在臨界點附近，代價是日後又得重新判斷一次假紅。
    maxWorkers: 4,
  },
})
