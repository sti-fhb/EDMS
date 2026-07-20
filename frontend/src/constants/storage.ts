/**
 * localStorage key 統一管理，禁止硬編碼字串。
 * 僅用於非敏感的 UI 偏好 / 一次性旗標；認證 token 一律 memory-only、禁存於此
 * （見 sti-frontend-modules 規則）。
 */
export const STORAGE_KEYS = {
  /** 歡迎橫幅「已顯示過」旗標：入口頁首次登入顯示一次、關閉後不再出現。 */
  WELCOME_DISMISSED: "edms.welcome_dismissed",
} as const
