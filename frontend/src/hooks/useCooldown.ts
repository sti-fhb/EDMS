import { useCallback, useEffect, useState } from "react"

/**
 * 倒數計時 hook（#74 驗證信寄送冷卻）：`start(seconds, key?)` 起算，每秒遞減至 0。
 * `active` 為 `remaining > 0`；`key` 記住此次冷卻所屬對象（如 Email），供呼叫端以
 * `active && key === 當前對象` 判斷——避免使用者換 Email 後仍被前一個 Email 的冷卻誤擋。
 * 倒數歸零後自動停止（effect cleanup 清 interval）。
 */
export function useCooldown() {
  const [remaining, setRemaining] = useState(0)
  const [key, setKey] = useState<string | null>(null)
  const active = remaining > 0

  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setRemaining((r) => (r <= 1 ? 0 : r - 1)), 1000)
    return () => clearInterval(id)
  }, [active])

  const start = useCallback((seconds: number, cooldownKey: string | null = null) => {
    setKey(cooldownKey)
    setRemaining(seconds > 0 ? Math.ceil(seconds) : 0)
  }, [])

  return { remaining, active, key, start }
}

/** 秒數轉 `m:ss` 顯示（倒數提示用）。 */
export function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}
