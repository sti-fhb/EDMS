/**
 * CSP nonce 讀取：nginx 以 sub_filter 將 index.html 的佔位字串換成每次請求的 nonce。
 */
import { afterEach, describe, expect, it } from "vitest"

import { CSP_NONCE_PLACEHOLDER, readCspNonce } from "./cspNonce"

const setMeta = (content: string) => {
  const meta = document.createElement("meta")
  meta.name = "csp-nonce"
  meta.content = content
  document.head.appendChild(meta)
}

afterEach(() => {
  document.head.querySelectorAll('meta[name="csp-nonce"]').forEach((m) => m.remove())
})

describe("readCspNonce", () => {
  it("nginx 已代換 → 回傳 nonce", () => {
    setMeta("0f3c9a7e5b1d4c2a8e6f0b9d7c5a3e1f")

    expect(readCspNonce()).toBe("0f3c9a7e5b1d4c2a8e6f0b9d7c5a3e1f")
  })

  it("仍為佔位字串（vite dev server，未經 nginx）→ undefined", () => {
    setMeta(CSP_NONCE_PLACEHOLDER)

    expect(readCspNonce()).toBeUndefined()
  })

  it("沒有 meta → undefined", () => {
    expect(readCspNonce()).toBeUndefined()
  })

  it("空字串 → undefined", () => {
    setMeta("")

    expect(readCspNonce()).toBeUndefined()
  })
})
