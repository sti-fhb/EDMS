import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"

/** 骨架佔位頁：顯示標題與「待實作」提示，實際內容由各 US 補上。 */
export function StubPage({ title, note }: { title: string; note?: string }) {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Alert severity="info">{note ?? "此頁為骨架佔位，功能將於後續 User Story 實作。"}</Alert>
    </Box>
  )
}
