import { useCallback } from "react"
import { useLocation, useNavigate } from "react-router-dom"

/**
 * 「返回上一頁」——退回瀏覽歷程的前一筆，沒有前一筆時導向 `fallback`。
 *
 * ## 為什麼不直接寫死目的地
 *
 * 同一個頁面可能從不同入口進入，寫死目的地等於假設只有一個入口。學習頁（ET06）
 * 原本寫死 `/et/my-courses`（ET03），但 #481 之後教師會從課程列表（ET01）的
 * 「全部課程」分頁點進來預覽——他按返回被丟到「我的課程」，那是一頁與他無關、
 * 多半還是空的清單。
 *
 * 退回歷程也順帶解決了**分頁與查詢條件**：`?scope=all` 存在網址上，退回時一併帶回，
 * 不需要在每個入口手動傳遞來源。
 *
 * ## ⚠️ 沒有上一頁時必須有 fallback
 *
 * 直接貼網址、重新整理、或從邀請信連結進來的人，歷程裡沒有本站的前一筆——
 * 此時 `navigate(-1)` 會把人帶**離開本站**。React Router 給工作階段的第一筆
 * location 的 `key` 固定是 `"default"`，用它分辨。
 *
 * ## ⚠️ 成對使用才有效
 *
 * 若 A 頁用本 hook 返回、而從 A 進入的 B 頁用 `navigate("/A")` 返回，B 的返回會
 * **push 一筆新的 A**，於是 A 的返回鍵退回到 B——看起來像返回鍵壞掉。
 * 一條路徑上的返回要嘛全部 pop、要嘛全部 push，不可混用。
 * 目前成對的是 `LearnPage` ↔ `SurveyFillPage`。
 */
export function useGoBack(fallback: string): () => void {
  const navigate = useNavigate()
  const { key } = useLocation()
  return useCallback(() => {
    if (key === "default") navigate(fallback)
    else navigate(-1)
  }, [key, navigate, fallback])
}
