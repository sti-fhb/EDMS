import AccessTimeIcon from "@mui/icons-material/AccessTime"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useRef, useState } from "react"

import { formatCountdown } from "./attemptSchemas"

/** 剩餘不到此秒數時轉紅——wireframe 的倒數為紅字，此處只在最後一分鐘強調。 */
const URGENT_SECONDS = 60

interface Props {
  /** 由**後端**算出的剩餘秒數（自 `STARTED_AT` 推導）。`null` = 不限時 → 本元件不渲染。 */
  remainingSec: number | null
  /**
   * 本地的絕對截止時點（毫秒），**由呼叫端在收到回應的當下錨定**。
   *
   * 不在本元件內以 `Date.now()` 算：那會發生在 render 期間（不純），而且錨定的時刻會
   * 比回應抵達晚——晚多少取決於 React 何時 render，是一個沒必要引入的誤差。
   */
  deadlineMs: number | null
  /** 倒數歸零時觸發一次自動提交。 */
  onExpire: () => void
}

/**
 * 作答倒數（AC 6）。
 *
 * ## 這只是「顯示」，不是把關
 *
 * 真正的逾時判定在後端：提交當下比對 `now > STARTED_AT + 時限` 就記為 `TIMEOUT`。
 * 本元件即使被停掉、被改時間、或分頁被凍結，學員也拿不到額外的作答時間。
 *
 * ⚠️ **起算值必須來自後端**——wireframe 引導頁明訂「中途離開或關閉視窗**仍持續扣
 * 時間**」，若改成每次載入從 `time_limit_min` 重新起算，關掉分頁再開就能無限延長。
 *
 * ## 由 deadline 推導，不是每秒減一
 *
 * 瀏覽器會把背景分頁的 `setInterval` 節流到**每分鐘一次**。若以「每次 tick 減 1 秒」
 * 累計，學員切去別的分頁三分鐘再回來，畫面上只會少 3 秒——與後端的實際剩餘時間差了
 * 快三分鐘，而後端才是算數的那個。改由「deadline − 現在時刻」推導後，節流只影響**更新
 * 頻率**，不影響**數值正確性**：回到分頁的第一個 tick 就會跳到正確的值。
 *
 * ## `onExpire` 只會觸發一次
 *
 * 少了這道，提交失敗（網路不穩）時會每秒重試一次，而每次都是一個註定失敗的請求。
 */
export function CountdownTimer({ remainingSec, deadlineMs, onExpire }: Props) {
  /** 最後一次 tick 的時刻；`null` = 還沒 tick 過（此時直接顯示後端給的秒數）。 */
  const [now, setNow] = useState<number | null>(null)
  const firedRef = useRef(false)
  const onExpireRef = useRef(onExpire)

  // `onExpire` 常是行內箭頭函式——放進依賴會讓計時器每次 render 重建；
  // 而在 render 期間寫 ref 是不允許的，故於 effect 內同步。
  useEffect(() => {
    onExpireRef.current = onExpire
  }, [onExpire])

  useEffect(() => {
    if (deadlineMs === null) return undefined
    firedRef.current = false
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [deadlineMs])

  // 第一個 tick 之前顯示後端原值——那本來就是當下最正確的數字，不必先猜一個
  const left =
    deadlineMs === null || now === null ? (remainingSec ?? 0) : Math.max(0, Math.ceil((deadlineMs - now) / 1000))

  useEffect(() => {
    if (deadlineMs === null || now === null || left > 0 || firedRef.current) return
    firedRef.current = true
    onExpireRef.current()
  }, [deadlineMs, now, left])

  // 不限時：**整塊不渲染**，而不是顯示「00:00」或「∞」
  if (remainingSec === null) return null

  const urgent = left <= URGENT_SECONDS
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      <AccessTimeIcon fontSize="small" color={urgent ? "error" : "action"} />
      <Typography variant="body2" color="text.secondary">
        剩餘時間
      </Typography>
      <Typography
        variant="h6"
        color={urgent ? "error" : "text.primary"}
        aria-label="剩餘作答時間"
        sx={{ fontVariantNumeric: "tabular-nums" }}
      >
        {formatCountdown(left)}
      </Typography>
    </Stack>
  )
}
