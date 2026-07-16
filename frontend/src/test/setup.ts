import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

// 每個 test 後清理 DOM，避免互相污染。
// 註：MSW（API 網路層 mock）於首個實際呼叫 API 的頁面 test 引入，骨架階段尚無 API。
afterEach(() => {
  cleanup()
})
