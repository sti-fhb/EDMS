import "@testing-library/jest-dom/vitest"

import { cleanup, configure } from "@testing-library/react"
import { afterAll, afterEach, beforeAll } from "vitest"

import { server } from "./server"

// `findBy*` 用的是 **asyncUtilTimeout**，不是 `it(...)` 的 testTimeout（後者 5000ms）。
// 兩個預算誰小誰綁住，而這個的預設只有 1000ms —— 整組跑時每檔的冷啟動（模組載入 +
// MSW handler + React 首次 render）量級約 4 秒，所以**各檔第一條測試的第一個等待**
// 會隨機被這 1000ms 吃掉，症狀是 `Unable to find an element with the text: ...`、
// 耗時 1~2 秒，看起來像元件壞了而不像假紅（#733）。
//
// ⛔ 對這一類加 `it(..., 15000)` 原理上無效 —— testTimeout 從來不是綁住它的那個。
//
// ⚠️ 本檔在 #733 之前**沒有**這行，但 `sti-testing.md` 已宣稱有 3000ms——
// 那個假宣稱讓人不會去查（「我們設過 3 秒了，所以問題不在這」）。改動前實測：
// `getConfig().asyncUtilTimeout = 1000`、失敗牆鐘 1019ms；改動後 3000 / 3016ms。
// `setup.test.ts` 會釘住本設定，拿掉這行它就紅。
configure({ asyncUtilTimeout: 3000 })

// jsdom 的 `Blob` 沒有 `.stream()`。凡是 `responseType: "blob"` 的請求（三處 CSV 匯出
// 都是），MSW 的 XHR 攔截器會把回應包成 undici `Response`，而那裡會呼叫 `blob.stream()`
// ——結果是 `TypeError: object.stream is not a function`，且它以 **unhandled rejection**
// 形式出現：測試不會停在這裡，只會在後面某個 `findByText` 找不到成功提示時失敗，看起來
// 像元件沒渲染。補上這個 polyfill 才驗得到匯出的成功路徑。
if (typeof Blob !== "undefined" && typeof Blob.prototype.stream !== "function") {
  Blob.prototype.stream = function stream(this: Blob): ReadableStream<Uint8Array<ArrayBuffer>> {
    // 在外層就取好 bytes，內層 `start` 便不需要拿到 `this`——否則得 `const blob = this`，
    // 那會被 `@typescript-eslint/no-this-alias` 擋下。
    const bytes = this.arrayBuffer().then((buffer) => new Uint8Array(buffer))
    return new ReadableStream<Uint8Array<ArrayBuffer>>({
      async start(controller) {
        controller.enqueue(await bytes)
        controller.close()
      },
    })
  }
}

// MSW：啟動 mock server（未定義的請求視為錯誤，強制每支測試明確 mock）。
beforeAll(() => server.listen({ onUnhandledRequest: "error" }))

// 每個 test 後清理 DOM、重置 handlers 並清 localStorage，避免互相污染。
afterEach(() => {
  cleanup()
  server.resetHandlers()
  // 純邏輯測試以檔首 `// @vitest-environment node` 跳過 jsdom（#376），那個環境沒有
  // `localStorage`——少了這道判定，那些檔案的**每一條**測試都會死在這行的
  // `ReferenceError`，而錯誤指向本檔、不指向測試，很難看出是環境問題。
  //
  // 用 `typeof` 而非 try/catch：後者會把真正的清理失敗一起吞掉，讓測試間的污染變成
  // 靜默問題。`cleanup()` 不需要同樣處理——它在 node 環境下實測不拋錯。
  if (typeof localStorage !== "undefined") localStorage.clear()
})

afterAll(() => server.close())
