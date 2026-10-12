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
 * 此時 `navigate(-1)` 會把人帶**離開本站**。判斷見 `isFirstEntry`。
 *
 * 沒有上一頁時以 **`replace`** 導向 fallback，並保留「第一筆」標記（#549）：push 的話，
 * 到了 fallback 頁再按返回會退回剛離開的這一頁（例如結果頁 / 問卷頁），而它同樣沒有
 * 上一頁——繞一圈。replace 之後 fallback 頁本身成為第一筆，它的返回再往它自己的 fallback 走。
 *
 * ## ⚠️ 成對使用才有效
 *
 * 若 A 頁用本 hook 返回、而從 A 進入的 B 頁用 `navigate("/A")` 返回，B 的返回會
 * **push 一筆新的 A**，於是 A 的返回鍵退回到 B——看起來像返回鍵壞掉。
 * 一條路徑上的返回要嘛全部 pop、要嘛全部 push，不可混用。
 * 目前成對的是 `LearnPage` ↔ `SurveyFillPage`，以及 `LearnPage` ↔ 測驗流程（#549：
 * 進測驗前以 `usePinQuizInUrl` 把學習頁釘成帶 `?quiz=`、作答頁以 `replace` 進結果頁、
 * 結果頁以本 hook 退回——整段測驗只佔學習頁那一格）。
 */
export function useGoBack(fallback: string): () => void {
  const navigate = useNavigate()
  const location = useLocation()
  const first = isFirstEntry(location)
  return useCallback(() => {
    if (first) navigate(fallback, { replace: true, state: { [FIRST_ENTRY]: true } })
    else navigate(-1)
  }, [first, navigate, fallback])
}

/** `location.state` 上標記「本筆是工作階段第一筆」的鍵。 */
const FIRST_ENTRY = "__firstEntry"

/**
 * 本筆是不是工作階段的第一筆（沒有本站的上一頁）。
 *
 * React Router 給第一筆 location 的 `key` 固定是 `"default"`。🔴 但**任何一次 `replace`
 * 都會換一個新 key**——位置仍是第一筆，key 卻不再是 `"default"`，`navigate(-1)` 便離站
 * （#549 security review：從邀請信連結開學習頁 → 開始作答時網址被 replace 成帶 `?quiz=`
 * → 學習頁的返回鍵離站）。故凡是在第一筆上 replace，都要以 `carryFirstEntry` 把標記帶到
 * 新的那一筆；本函式兩者皆認。
 *
 * ⛔ 不要改用 `window.history.state.idx`：那是 React Router 未公開的內部欄位，而且測試用的
 * memory router 根本不寫 `window.history`。
 */
export function isFirstEntry(location: { key: string; state: unknown }): boolean {
  if (location.key === "default") return true
  const { state } = location
  return typeof state === "object" && state !== null && (state as Record<string, unknown>)[FIRST_ENTRY] === true
}

/**
 * `replace` 時要帶的 state：本筆是第一筆時，在 `nextState` 上加上第一筆標記。
 *
 * 呼叫端：在**目前這一筆**上 `replace` 的地方（`usePinQuizInUrl`、作答頁提交進結果頁）。
 * `nextState` 非物件時（`null` / `undefined`）以空物件起算。
 */
export function carryFirstEntry(location: { key: string; state: unknown }, nextState: unknown): unknown {
  if (!isFirstEntry(location)) return nextState
  const base = typeof nextState === "object" && nextState !== null ? nextState : {}
  return { ...base, [FIRST_ENTRY]: true }
}
