import LockIcon from "@mui/icons-material/Lock"
import Alert from "@mui/material/Alert"
import AlertTitle from "@mui/material/AlertTitle"
import Box from "@mui/material/Box"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

/**
 * 無權限畫面（#250）。
 *
 * 側欄隱藏入口只擋「看得到的路」——直接輸入網址或用舊書籤仍會進到頁面，此時後端回 403，
 * 但頁面本身會停在載入中或渲染出空殼（看起來像壞掉）。本元件讓路由守衛把它換成明確說明。
 *
 * 真正的權限邊界在後端（`require_any_module_admin` / `get_dm_reviewer_context` 等），
 * 本元件只負責把「已被擋下」這件事講清楚。
 */
export function AccessDenied({ reason }: { reason: string }) {
  return (
    <Box sx={{ p: 3 }}>
      <Alert severity="error" icon={<LockIcon />}>
        <AlertTitle>無存取權限（HTTP 403）</AlertTitle>
        <Stack spacing={0.5}>
          <Typography variant="body2">{reason}</Typography>
          <Typography variant="caption" color="text.secondary">
            如需使用此功能，請洽模組管理者為您指派對應角色。
          </Typography>
        </Stack>
      </Alert>
    </Box>
  )
}
