import { useEffect, useRef } from "react"

interface Options {
  /** 只在作答進行中掛監聽；已提交 / 載入中不掛。 */
  enabled: boolean
  onLeave: () => void
}

/**
 * 學員離開作答視窗時自動提交（SA 裁示 2026-09-09）。
 *
 * ## 為何同時聽兩個事件
 *
 * | 事件 | 抓得到 | 抓不到 |
 * |---|---|---|
 * | `visibilitychange`（`document.hidden`）| 切換分頁、視窗最小化 | **並排的第二個視窗**——本分頁仍然可見 |
 * | `window.blur` | 切換到任何其他視窗或程式 | — |
 *
 * 只聽 `visibilitychange` 會漏掉「並排開第二個視窗對照上一次作答的答案卷」，而那正是這個
 * 機制要擋的用法——只擋切分頁等於做了一個看起來有防護、實際擋不到目標的東西。
 *
 * ## 代價要說清楚
 *
 * `blur` 也會被作業系統通知、點瀏覽器網址列、開 devtools 觸發，而誤觸的代價是**一次作答
 * 次數**。故此機制必須在作答前與作答中都明白告知學員（`QuizIntroPanel` 的注意事項與
 * `QuizAnswerPage` 上方的常駐警示）。若日後認定誤觸太兇，拿掉 `blur` 這一行即可退回
 * 「只擋切分頁」。
 *
 * ## 這是提醒，不是強制
 *
 * 停掉 JavaScript、改用兩台裝置都繞得過。真正的防弊手段是題庫抽樣（另立 issue），
 * 見 `spec_us6` 對「交白卷換答案」殘餘風險的說明。
 */
export function useAutoSubmitOnLeave({ enabled, onLeave }: Options) {
  // 回呼放進 ref：`onLeave` 每次 render 都是新的函式，直接當依賴會讓監聽器不斷解除重掛，
  // 而恰好落在解除與重掛之間的離開事件會整個漏掉。
  const handler = useRef(onLeave)
  useEffect(() => {
    handler.current = onLeave
  })

  useEffect(() => {
    if (!enabled) return
    const leave = () => handler.current()
    const onVisibility = () => {
      // `visibilitychange` 在「變回可見」時也會觸發——只在轉為隱藏時才算離開
      if (document.hidden) leave()
    }
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("blur", leave)
    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("blur", leave)
    }
  }, [enabled])
}
