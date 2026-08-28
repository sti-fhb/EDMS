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

  // ── payload：帶結構化細節的錯誤（對應後端 AppError.extra，#204）────────────

  it("業務錯誤帶回原始 body 供取用結構化細節", () => {
    // ET 發布檢核未通過（ET_PUBLISH_001）會在 body 帶 blockers 清單——
    // 沒有這個欄位，前端只能顯示「發布條件未滿足」，教師得自己猜哪裡不合格。
    const blockers = [{ code: "NO_TAG", message: "課程至少須掛 1 個受訓單位標籤", target_id: null }]
    const got = toApiError(
      withResponse(422, { error_code: "ET_PUBLISH_001", error_message: "發布條件未滿足", blockers }),
    )
    expect(got.errorCode).toBe("ET_PUBLISH_001")
    expect(got.payload?.blockers).toEqual(blockers)
  })

  it("沒有額外欄位時 payload 仍是那個 body、不是 undefined", () => {
    const got = toApiError(withResponse(404, { error_code: "ET_COURSE_001", error_message: "查無此課程" }))
    expect(got.payload).toEqual({ error_code: "ET_COURSE_001", error_message: "查無此課程" })
  })

  it("完全沒有 response 時無 payload", () => {
    expect(toApiError(new Error("boom")).payload).toBeUndefined()
  })

  it("伺服器端錯誤（無 error_message）不帶 payload", () => {
    // 那條路徑的 body 是 FastAPI 預設或反向代理錯誤頁，沒有結構化細節可取
    expect(toApiError(withResponse(500, { detail: "Internal Server Error" })).payload).toBeUndefined()
  })

  it("retryAfter 仍獨立回傳、不必從 payload 取", () => {
    // retryAfter 早於 payload 存在且已有多處呼叫端，維持獨立欄位（與後端對稱）
    const got = toApiError(withResponse(429, { error_code: "X", error_message: "太頻繁", retry_after: 30 }))
    expect(got.retryAfter).toBe(30)
    expect(got.payload?.retry_after).toBe(30)
  })
})
