/**
 * tiptap 自行注入的 <style data-tiptap-style> 必須帶 CSP nonce。
 *
 * CSP style-src 不放行 'unsafe-inline'：tiptap 不經 Emotion、也不讀全域 nonce，只認 useEditor 的
 * `injectNonce`。漏帶時編輯器照樣可打字，但 ProseMirror 的基礎樣式（如 white-space: pre-wrap）
 * 被瀏覽器擋掉，換行與空白顯示會跑掉。
 */
import { render, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { RichTextEditor } from "./RichTextEditor"

const NONCE = "0f3c9a7e5b1d4c2a8e6f0b9d7c5a3e1f"

afterEach(() => {
  document.head.querySelectorAll('meta[name="csp-nonce"], style[data-tiptap-style]').forEach((el) => el.remove())
})

describe("RichTextEditor：CSP nonce", () => {
  it("頁面帶 nonce → tiptap 注入的 <style> 帶同一個 nonce", async () => {
    const meta = document.createElement("meta")
    meta.name = "csp-nonce"
    meta.content = NONCE
    document.head.appendChild(meta)

    render(<RichTextEditor value="<p>說明</p>" onChange={() => {}} />)

    await waitFor(() => expect(document.querySelector("style[data-tiptap-style]")).not.toBeNull())
    expect(document.querySelector("style[data-tiptap-style]")?.getAttribute("nonce")).toBe(NONCE)
  })
})
