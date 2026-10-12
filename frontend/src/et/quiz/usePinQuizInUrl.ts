import { useCallback } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { carryFirstEntry } from "../../hooks/useGoBack"

/**
 * 把**目前的學習頁網址**原地換成帶 `?quiz={quizId}`——離開學習頁進測驗之前呼叫（#549）。
 *
 * ## 為什麼要先釘住
 *
 * 測驗流程（學習頁 → 作答 → 結果）結束時，結果頁以 `useGoBack` **退回**學習頁，而不是
 * push 一筆新的（push 會讓學習頁的返回鍵退回結果頁，即 #549）。退回去的是**離開時的
 * 那一筆**學習頁——若那一筆沒有 `?quiz=`，學習頁會落回 `last_item_id` 推導的項目，
 * 而那正是 #416 加 `?quiz=` 要避開的（`last_item_id` 被 `openable` 過濾，鎖定時被靜默丟棄）。
 *
 * 用 `replace`：只改這一筆，不新增歷程。其他 query 參數原樣保留。
 *
 * ## 呼叫端以 `await` 等它完成再導向下一頁
 *
 * 本專案是 data router（`createBrowserRouter`），`navigate` 回傳 Promise。等它完成再發第二次
 * 導向，讓「先換網址、再進下一頁」的順序不依賴 router 的內部排程。
 *
 * ⚠️ 這是**防禦性**寫法，目前沒有測試守住：2026-10-12 #549 變異檢查把 `await` 拿掉，測試
 * 照樣全過（無 loader 的 router 下，兩次導向沒有互相中斷）。⛔ 不要把它寫成「不 await 會壞」
 * ——那個說法沒有證據；也不要因為「拿掉也沒紅」就刪掉它。
 */
export function usePinQuizInUrl(quizId: number): () => Promise<void> {
  const navigate = useNavigate()
  const location = useLocation()
  const { pathname, search, hash } = location
  return useCallback(async () => {
    const params = new URLSearchParams(search)
    if (params.get("quiz") === String(quizId)) return
    params.set("quiz", String(quizId))
    // hash 與 state 原樣帶過去——只動 `?quiz=`，這一筆的其餘內容不變。
    // 🔴 本筆若是工作階段第一筆（例如從邀請信連結進來），replace 會換掉 `"default"` key，
    // 學習頁的返回鍵便以為有上一頁而離站——`carryFirstEntry` 把「第一筆」標記帶過去
    await navigate(
      { pathname, search: `?${params.toString()}`, hash },
      { replace: true, state: carryFirstEntry(location, location.state) },
    )
  }, [navigate, location, pathname, search, hash, quizId])
}
