import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Container from "@mui/material/Container"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

/**
 * 登入後模組入口頁（骨架）。
 * ET 卡恆顯示；DM 卡恆顯示、無 DM 角色者呈「未開通」鎖定（research §12）。
 * 卡片狀態實際由「我的模組角色摘要」端點決定，骨架先放 placeholder。
 * DP 後台入口不設於此（僅由 ET / DM 管理選單進入）。
 */
export function PortalPage() {
  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      <Typography variant="h4" gutterBottom>
        EDMS 模組入口
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={3} sx={{ mt: 3 }}>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="h6">教育訓練（ET）</Typography>
            <Typography variant="body2" color="text.secondary">
              教育訓練文件與課程（骨架 placeholder）。
            </Typography>
          </CardContent>
        </Card>
        <Card sx={{ flex: 1, opacity: 0.6 }}>
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Typography variant="h6">文件管理（DM）</Typography>
              <Typography variant="caption" color="text.secondary">
                🔒 未開通
              </Typography>
            </Box>
            <Typography variant="body2" color="text.secondary">
              請洽您的單位主管或管理者開通（骨架 placeholder）。
            </Typography>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  )
}
