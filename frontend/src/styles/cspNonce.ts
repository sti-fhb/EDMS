/**
 * CSP nonce。
 *
 * CSP 的 style-src 不放行 'unsafe-inline'，改以 nonce 放行執行期注入的 <style>：
 * MUI／Emotion（main.tsx 的 Emotion cache）與 tiptap 編輯器（RichTextEditor 的 injectNonce）。
 * nonce 由 nginx 每次請求產生（$request_id），以 sub_filter 代換 index.html 中
 * `<meta name="csp-nonce">` 的佔位字串，CSP 標頭帶同一個值（見 nginx/nginx.conf、nginx/security-headers.conf）。
 *
 * vite dev server 不經 nginx，meta 仍為佔位字串，也沒有 CSP 標頭 —— 視為沒有 nonce。
 */
export const CSP_NONCE_PLACEHOLDER = "__CSP_NONCE__"

export function readCspNonce(): string | undefined {
  const content = document.querySelector<HTMLMetaElement>('meta[name="csp-nonce"]')?.content
  if (!content || content === CSP_NONCE_PLACEHOLDER) return undefined
  return content
}
