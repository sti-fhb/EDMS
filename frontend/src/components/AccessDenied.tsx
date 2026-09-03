import LockIcon from "@mui/icons-material/Lock"
import Alert from "@mui/material/Alert"
import AlertTitle from "@mui/material/AlertTitle"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"

/**
 * 無權限畫面（#250）——**所有**權限不足的頁面統一顯示這一種，文案不因頁面而異。
 *
 * 側欄隱藏入口只擋「看得到的路」；直接輸入網址或用舊書籤仍會進到頁面，此時後端回 403，
 * 但各頁的處理方式不一致（停在載入中、渲染空殼、或彈一則 Snackbar），看起來像壞掉。
 * 由路由守衛（`layouts/RequireAccess.tsx`）改為一律換成本畫面。
 *
 * 真正的權限邊界在後端（`require_any_module_admin` / `get_dm_reviewer_context` /
 * service 層 `DM_AUTH_003` 等），本元件只負責把「已被擋下」講清楚。
 */
export function AccessDenied() {
  return (
    <Box sx={{ p: 3 }}>
      <Alert severity="error" icon={<LockIcon />}>
        <AlertTitle>無權限存取此功能</AlertTitle>
        <Typography variant="body2" color="text.secondary">
          如需使用此功能，請洽模組管理者為您指派對應角色。
        </Typography>
      </Alert>
    </Box>
  )
}
