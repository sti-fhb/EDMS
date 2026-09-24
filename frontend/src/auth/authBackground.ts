/** 認證頁面共用漸層背景（登入 overlay 與信中連結落點頁一致：淺綠 → 米白 → 淺粉，對齊 TBMS 登入頁）。 */
export const AUTH_BG_GRADIENT = "linear-gradient(135deg, #e4eadc 0%, #f2f5ee 40%, #fdf2f2 100%)"

/**
 * 登入頁副標（系統英文名）之文字色，與 TBMS `loginTheme.subtitleColor` 同值。
 *
 * 不用 `text.secondary`（EDMS 為 `#999999`）或 `text.disabled`（MUI 預設半透明黑）——
 * 兩者值都不同，換過去等於改了顏色；而此色本來就已與主專案一致，本次不應動它。
 * 集中於此與 `AUTH_BG_GRADIENT` 同一慣例，避免色碼散落在元件內。
 * 此例外已記載於 `docs/ref/ui-design-guide.md` §23「已記載的例外：認證頁專屬色」。
 */
export const AUTH_SUBTITLE_COLOR = "#78716c"