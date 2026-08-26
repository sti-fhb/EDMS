import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { coursesApi } from "./coursesService"
import { QUERY_KEYS } from "../../constants/queryKeys"

/**
 * ET01 課程列表（US7 / Issue #7）——**本頁於 #202 僅為骨架**。
 *
 * 卡片網格、關鍵字搜尋、擁有權篩選（全部 / 我建立的）屬 #7 範圍。此處只提供
 * 「+ 新增課程」入口——ET02 是課程列表的子頁而非側欄項目，沒有這顆按鈕的話
 * #202 交付的課程編輯頁將無路可達。
 *
 * **按鈕依 `can_create_course` 顯示**：僅具教師角色者可建立課程（SA 裁示 Q2）。
 * 前端無從自行推導角色——JWT 刻意不含角色、`module-summary` 只回布林——故由後端
 * 回「能力」而非「角色」（比照 DM `Capabilities`），使授權判斷只有一個來源。
 */
export function EtCourseListPage() {
  const navigate = useNavigate()
  const { data: capabilities } = useQuery({
    queryKey: QUERY_KEYS.etCourses.capabilities(),
    queryFn: coursesApi.getCapabilities,
  })

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5">課程列表</Typography>
        {capabilities?.can_create_course && (
          <Button
            variant="contained"
            startIcon={<AddCircleOutlineIcon />}
            onClick={() => navigate("/et/courses/new")}
          >
            新增課程
          </Button>
        )}
      </Stack>
      <Alert severity="info">
        ET01 課程列表（US7 / #7）：課程卡片網格、關鍵字搜尋與擁有權篩選待該 issue 實作。
        {capabilities?.can_create_course
          ? "目前可由右上「新增課程」進入 ET02 課程編輯頁。"
          : "建立課程需具備教師角色。"}
      </Alert>
    </Box>
  )
}
