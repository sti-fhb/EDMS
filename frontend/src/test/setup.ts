import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll } from "vitest"

import { server } from "./server"

// MSW：啟動 mock server（未定義的請求視為錯誤，強制每支測試明確 mock）。
beforeAll(() => server.listen({ onUnhandledRequest: "error" }))

// 每個 test 後清理 DOM 並重置 handlers，避免互相污染。
afterEach(() => {
  cleanup()
  server.resetHandlers()
})

afterAll(() => server.close())
