import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll } from "vitest"

import { server } from "./server"

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
  localStorage.clear()
})

afterAll(() => server.close())
