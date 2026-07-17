import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import CircularProgress from "@mui/material/CircularProgress"
import Container from "@mui/material/Container"
import Snackbar from "@mui/material/Snackbar"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { authApi } from "../auth/authService"
import { QUERY_KEYS } from "../constants/queryKeys"

/**
 * 登入後模組入口頁（spec_us1 FR-07）。
 * ET 卡恆可進入（學員預設）；DM 卡具任一角色＝可進入、無＝「未開通」鎖定（點擊提示 DP-MSG-LOGIN-008、不進入）。
 * 卡片狀態由 module-summary 端點決定；首次登入顯示歡迎橫幅（可關閉）。DP 後台入口不設於此。
 */
export function PortalPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEYS.auth.moduleSummary(),
    queryFn: authApi.moduleSummary,
  })
  const [showWelcome, setShowWelcome] = useState(true)
  const [lockedHint, setLockedHint] = useState(false)

  if (isPending) {
    return (
      <Container maxWidth="md" sx={{ py: 6, textAlign: "center" }}>
        <CircularProgress aria-label="載入中" />
      </Container>
    )
  }

  if (isError) {
    return (
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Alert severity="error">無法載入模組資訊，請稍後再試</Alert>
      </Container>
    )
  }

  const dmHasRole = data.dm.has_role

  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      {showWelcome && (
        <Alert severity="success" sx={{ mb: 3 }} onClose={() => setShowWelcome(false)}>
          歡迎使用 EDMS 教育訓練文件管理系統
        </Alert>
      )}
      <Typography variant="h4" gutterBottom>
        EDMS 模組入口
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={3} sx={{ mt: 3 }}>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="h6">教育訓練（ET）</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              教育訓練文件與課程。
            </Typography>
            <Button variant="contained" href="/et">
              進入
            </Button>
          </CardContent>
        </Card>
        {dmHasRole ? (
          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Typography variant="h6">文件管理（DM）</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                文件管理與審閱。
              </Typography>
              <Button variant="contained" href="/dm">
                進入
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card
            sx={{ flex: 1, opacity: 0.6, cursor: "not-allowed" }}
            onClick={() => setLockedHint(true)}
            role="button"
            aria-label="文件管理未開通"
          >
            <CardContent>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Typography variant="h6">文件管理（DM）</Typography>
                <Typography variant="caption" color="text.secondary">
                  🔒 未開通
                </Typography>
              </Box>
              <Typography variant="body2" color="text.secondary">
                尚未開通文件管理權限，請洽您的單位主管或管理者。
              </Typography>
            </CardContent>
          </Card>
        )}
      </Stack>
      <Snackbar
        open={lockedHint}
        autoHideDuration={4000}
        onClose={() => setLockedHint(false)}
        message="尚未開通文件管理權限，請洽您的單位主管或管理者"
      />
    </Container>
  )
}
