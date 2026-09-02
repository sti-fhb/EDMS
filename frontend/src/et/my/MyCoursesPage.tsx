import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline"
import BookIcon from "@mui/icons-material/Book"
import CheckCircleIcon from "@mui/icons-material/CheckCircle"
import DateRangeIcon from "@mui/icons-material/DateRange"
import FormatListNumberedIcon from "@mui/icons-material/FormatListNumbered"
import HourglassTopIcon from "@mui/icons-material/HourglassTop"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardActionArea from "@mui/material/CardActionArea"
import Chip from "@mui/material/Chip"
import Grid from "@mui/material/Grid"
import LinearProgress from "@mui/material/LinearProgress"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import type { ReactNode } from "react"

import { JoinCourseDialog } from "./JoinCourseDialog"
import { COMPLETION_STATUS_LABEL } from "./myCoursesSchemas"
import type { MyCourseRow } from "./myCoursesSchemas"
import { myCoursesApi } from "./myCoursesService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { formatDateTime } from "../../utils/date"

/**
 * ET04 我的課程（US4 / #247）——學員預設首頁。
 *
 * ## 三項 spec 條目本 issue 到不了
 *
 * | spec | 為何 | 做到哪 |
 * |---|---|---|
 * | AC 6 點卡片進 ET05、定位上次進度 | `ET-5` 未實作 | 卡片可點，目的地暫留本頁並提示 |
 * | AC 5 / 13 已關閉課程唯讀回看 | `ET-11` 未實作，課程無法變 CLOSED | 「已關閉」標示與可見性已完成 |
 * | 卡片「當前進度」 | 依賴 `ET_PROGRESS`（`ET-5`）| 進度條已備妥，值恆為 0 |
 *
 * 三者都是**依賴未到位**而非漏做。可見性邏輯現在就寫——等 `ET-11` 交付才補，
 * 那時沒有人會記得這裡少了一段。
 *
 * ## 沒有「退出課程」
 *
 * FR-ET-US4-06：學員無主動退出能力，退場僅能由教師於 US9 執行「移除學員」。
 * 後端連端點都沒有——少寫一個端點就是這條規則的執行方式。
 */
export function EtMyCoursesPage() {
  const { message } = useNotification()
  const [joinOpen, setJoinOpen] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: QUERY_KEYS.etMyCourses.list(),
    queryFn: myCoursesApi.list,
  })

  const summary = data?.summary
  const courses = data?.courses ?? []

  /**
   * 點擊課程卡片（AC 6）。
   *
   * `ET-5` 章節學習頁未實作——**先提示而非 `navigate` 到不存在的路由**，後者會給
   * 學員一個白畫面，看起來像壞掉而不像還沒做。
   *
   * ⚠️ **只在點卡片時呼叫**。加入成功 / 已加入的路徑上**不要**再呼叫它：那些路徑
   * 自己已經有一則訊息，接著再送一則會把前一則蓋掉——實測時「您已加入此課程」就是
   * 這樣變成「章節學習頁尚未開放」的。
   *
   * 🔴 **`ET-5` 交付時**：改成收 `courseId` 並 `navigate(\`/et/courses/${id}/learn\`)`，
   * 並讓加入成功 / 已加入兩條路徑改為導向（那時導向取代訊息，不會再互相覆蓋）。
   */
  function openCourse() {
    message.info("章節學習頁尚未開放")
  }

  function handleJoined(_courseId: number, pendingOpen: boolean) {
    void refetch()
    // `ET-5` 交付前只給一則訊息、不導向——學員留在清單上就看得到剛加入的課程。
    message.success(pendingOpen ? "已加入，課程開放後將出現於清單" : "已加入課程")
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        我的課程
      </Typography>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <StatCard label="已加入課程" value={summary?.joined ?? 0} icon={<BookIcon />} />
        <StatCard label="進行中" value={summary?.in_progress ?? 0} icon={<HourglassTopIcon />} color="warning.main" />
        <StatCard label="未開始" value={summary?.not_started ?? 0} icon={<FormatListNumberedIcon />} />
        <StatCard label="已完成" value={summary?.completed ?? 0} icon={<CheckCircleIcon />} color="success.main" />
        <Grid size={{ xs: 6, md: 2.4 }}>
          <Paper
            variant="outlined"
            onClick={() => setJoinOpen(true)}
            sx={{
              p: 2,
              height: "100%",
              cursor: "pointer",
              borderColor: "success.main",
              bgcolor: "success.50",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}
            role="button"
            aria-label="加入新課程"
          >
            <AddCircleOutlineIcon color="success" />
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              加入新課程
            </Typography>
            <Typography variant="caption" color="text.secondary">
              輸入邀請碼
            </Typography>
          </Paper>
        </Grid>
      </Grid>

      {!isLoading && courses.length === 0 && (
        <Alert severity="info">尚未加入任何課程，點「加入新課程」輸入邀請碼開始。</Alert>
      )}

      <Grid container spacing={2}>
        {courses.map((course) => (
          <Grid key={course.course_id} size={{ xs: 12, md: 4 }}>
            <CourseCard course={course} onOpen={openCourse} />
          </Grid>
        ))}
      </Grid>

      <JoinCourseDialog
        open={joinOpen}
        onClose={() => setJoinOpen(false)}
        onJoined={handleJoined}
        onAlreadyJoined={(_courseId, pendingOpen) => {
          // 只送一則。`ET-5` 交付後這裡改成導向該課程（AC 10）。
          //
          // 未開放時**必須說明白**：光說「您已加入此課程」而清單是空的（AC 4），
          // 學員會以為系統壞了——實測就是這樣回報的。
          message.info(pendingOpen ? "您已加入此課程，將於課程開放後出現於清單" : "您已加入此課程")
        }}
      />
    </Box>
  )
}

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string
  value: number
  icon: ReactNode
  color?: string
}) {
  return (
    <Grid size={{ xs: 6, md: 2.4 }}>
      <Paper variant="outlined" sx={{ p: 2, height: "100%", textAlign: "center" }}>
        <Box sx={{ color: color ?? "text.secondary" }}>{icon}</Box>
        <Typography variant="h5" sx={{ color }}>
          {value}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
      </Paper>
    </Grid>
  )
}

function CourseCard({ course, onOpen }: { course: MyCourseRow; onOpen: () => void }) {
  const closed = course.status === "CLOSED"

  return (
    <Card variant="outlined" sx={{ height: "100%" }}>
      <CardActionArea onClick={onOpen} sx={{ p: 2, height: "100%", alignItems: "flex-start" }}>
        <Stack spacing={1} sx={{ width: "100%" }}>
          <Stack direction="row" spacing={0.5}>
            <Chip
              size="small"
              label={COMPLETION_STATUS_LABEL[course.completion_status]}
              color={course.completion_status === "COMPLETED" ? "success" : "warning"}
            />
            {closed && <Chip size="small" label="已關閉" />}
          </Stack>

          <Typography variant="subtitle1">{course.course_name}</Typography>

          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {course.tags.map((tag) => (
              <Chip key={tag} size="small" variant="outlined" label={tag} />
            ))}
          </Stack>

          <Typography variant="caption" color="text.secondary">
            <DateRangeIcon fontSize="inherit" sx={{ verticalAlign: "middle", mr: 0.5 }} />
            閱課期間 {formatDateTime(course.open_start_at)} ～ {formatDateTime(course.open_end_at)}
          </Typography>

          <LinearProgress variant="determinate" value={course.progress_pct} />
          <Typography variant="caption" color="text.secondary">
            完成 {course.progress_pct}%｜{course.chapter_count} 章節
          </Typography>
        </Stack>
      </CardActionArea>
    </Card>
  )
}
