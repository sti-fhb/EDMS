import Chip from "@mui/material/Chip"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

/**
 * ET03 三個區塊共用的標題列（wireframe 的 `badge bg-secondary` + 標題 + 說明）。
 *
 * 區塊編號是**規格用語**（`spec_us9` 稱「區塊 1 / 2 / 3」），保留在畫面上讓教師回報問題
 * 時能直接指名哪一區。
 */
export function BlockHeading({ index, title, note }: { index: number; title: string; note: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
      <Chip size="small" label={`區塊 ${index}`} />
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        {title}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        （{note}）
      </Typography>
    </Stack>
  )
}
