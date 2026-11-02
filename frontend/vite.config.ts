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
    // 2026-10-30（#733）重量，**105 支測試檔 / 1372 條**、12 邏輯核心、main `94b1d14a`。
    // 兩輪連續跑，開跑前各實測 **0 個 node、0 個 python**（⚠️ 兩種 runtime 都要查，只查
    // node 漏得掉 pytest）：
    //
    // | 條件 | 結果 | 牆鐘 | environment |
    // |---|---|---|---|
    // | `--maxWorkers=12`（模擬預設）| **14 檔紅 / 33 條紅**（全為 `Test timed out in 5000ms`）| 453.68s | 1764.04s |
    // | **`maxWorkers:4`（本設定）** | **105/105、1372/1372 全綠** | 523.64s | **654.59s** |
    //
    // ⭐ **可靠性的差距是決定性的**：同一個 commit、同樣的乾淨機器，差別只有併發度，
    // 而 33 條紅全是飢餓造成的 `testTimeout`。`environment` 2.7 倍即其指紋。
    //
    // 🔴 **但「順便變快」那半已經不成立了，別再引用。** 2026-09-18（#376）在 **74 檔**時
    // 量到空閒下 268s vs 487s（快 1.8 倍），據此寫過「本設定同時改善可靠性與速度」——
    // 到了 105 檔，12 worker 的牆鐘反而較短（453s vs 523s）。
    //
    // ⚠️ 而且那個 453s **不能拿來宣稱「預設比較快」**：它有 33 條在 5 秒就放棄、根本沒跑完，
    // 牆鐘天生偏短。這個比較只能得到「**速度不再是支持本設定的理由**」，不能反過來用。
    // 留本設定的理由現在只有一個：可靠性。一個理由就夠，但要說對是哪一個。
    //
    // 📌 同設定的跑次變異約 9%（10-29 在 `ba40879d` 量到 478.42s，本次 523.64s，兩次都乾淨）。
    // ⇒ **單輪牆鐘分辨不出 10% 以內的差異**，要比較就跑兩輪以上。
    //
    // ⚠️ 效能量測前先確認機器空閒，且 🔴 **要逐行看 CommandLine、不要只數行程數**
    // （`ps -W | grep -c node.exe` 這種會同時有高估與低估的陷阱，詳見
    // `.claude/rules/sti-testing.md`〈量測與 A/B 的前提〉）。
    //
    // ⚠️ `maxWorkers` 是**每個 vitest 行程**的上限，不是機器層級的。三個 session 各跑一次
    // 就是 3 × 4 = 12 個並行 fork，又回到原點。多 session 並行時的紅**不代表本設定失效**。
    //
    // 🔴 平行度越高越糟，這點反直覺：GitHub CI（4 vCPU）用同一份設定與指令一直是綠的，
    // 紅的只有核心數更多的開發機。看到「CI 綠、本機紅」時容易誤判為本機環境髒了。
    //
    // ⛔ 不往上調到 6 或 8：4 已滿足全綠，再往上只會更接近飢餓的懸崖，而這套測試還在長大
    // （74 → 105 檔只花了六週）。為省數十秒把設定放在臨界點附近，代價是日後又得重新判斷
    // 一次假紅。
    maxWorkers: 4,
  },
})
