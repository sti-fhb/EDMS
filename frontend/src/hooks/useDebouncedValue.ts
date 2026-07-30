import { useEffect, useState } from "react"

/**
 * 去抖動值：`value` 停止變動 `delayMs` 毫秒後才更新回傳值。
 * 用於輸入即時查詢——避免每個按鍵字元都觸發一次查詢。
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return debounced
}
