import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

/**
 * ET03 三個區塊共用的標題列（wireframe 的 `badge bg-secondary` + 標題 + 說明）。
 *
 * ## 區塊編號已移除（#359 第 3 項，2026-09-17 使用者裁示）
 *
 * ⚠️ **這裡原本寫著「保留編號讓教師回報問題時能指名哪一區」，那個理由已被推翻**——
 * 手測回饋是：三個區塊在同一頁上下排列、各有標題，教師說的是「作答明細那一塊」而不是
 * 「區塊 2」，編號對他不構成指稱工具，只是多一顆看不懂的 chip。
 *
 * ⛔ **不要因為 `spec_us9` 仍稱「區塊 1 / 2 / 3」就把它加回來。** 那是**規格內部的**
 * 條列用語（供 FR 與測試項目引用），不代表畫面要顯示。規格用語與畫面文字是兩回事，
 * 這正是本次裁示要分開的東西。
 */
export function BlockHeading({ title, note }: { title: string; note: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        {title}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        （{note}）
      </Typography>
    </Stack>
  )
}
