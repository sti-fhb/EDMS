import { describe, expect, it } from "vitest"

import { toApiError } from "./http"

/**
 * 錯誤正規化——**三種情形必須分得開**。
 *
 * 2026-08-26 於 #203 實測時，一個 500（開發庫少套 migration）在畫面上顯示成
 * 「系統連線異常」，把排查方向帶去查網路，實際上網路好得很。
 */

const withResponse = (status: number, data: unknown) => ({ response: { status, data } })

describe("toApiError", () => {
  it("完全沒有 response 時視為連線問題", () => {
    // 斷網、後端沒起來、CORS 被擋——axios 例外不帶 response
    const got = toApiError({ message: "Network Error" })
    expect(got).toEqual({ status: 0, errorCode: "NETWORK_ERROR", errorMessage: "系統連線異常，請稍後再試" })
  })

  it("後端業務錯誤原樣顯示", () => {
    const got = toApiError(
      withResponse(422, { error_code: "ET_MATERIAL_002", error_message: "教材須至少提供影片、文件或說明文字其中一項" }),
    )
    expect(got.status).toBe(422)
    expect(got.errorCode).toBe("ET_MATERIAL_002")
    expect(got.errorMessage).toBe("教材須至少提供影片、文件或說明文字其中一項")
  })

  it("429 帶回可重試秒數", () => {
    const got = toApiError(
      withResponse(429, { error_code: "COMMON_429", error_message: "請求過於頻繁", retry_after: 30 }),
    )
    expect(got.retryAfter).toBe(30)
  })

  it("未處理之 500 顯示為伺服器錯誤而非連線異常", () => {
    // FastAPI 的未處理例外回 {"detail": "Internal Server Error"}——沒有 error_message
    const got = toApiError(withResponse(500, { detail: "Internal Server Error" }))
    expect(got.errorCode).toBe("SERVER_ERROR")
    expect(got.errorMessage).not.toContain("連線")
    expect(got.errorMessage).toContain("500")
  })

  it("伺服器錯誤訊息帶上 HTTP 狀態碼供回報", () => {
    expect(toApiError(withResponse(502, "<html>Bad Gateway</html>")).errorMessage).toContain("502")
  })

  it("回應 body 為空字串時仍視為伺服器錯誤", () => {
    const got = toApiError(withResponse(503, ""))
    expect(got.errorCode).toBe("SERVER_ERROR")
    expect(got.status).toBe(503)
  })

  it("有 error_message 但無 error_code 時不誤標為連線問題", () => {
    const got = toApiError(withResponse(400, { error_message: "參數有誤" }))
    expect(got.errorCode).toBe("UNKNOWN_ERROR")
    expect(got.errorMessage).toBe("參數有誤")
  })
})
