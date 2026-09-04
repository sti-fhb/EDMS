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
import { useNavigate, useSearchParams } from "react-router-dom"

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
  const navigate = useNavigate()
  const { message } = useNotification()
  const [searchParams] = useSearchParams()

  // 教師以「複製邀請連結」/ QR Code 傳出的網址帶 `?code=`（#273）。落地即開啟加入視窗
  // 並預填該碼——不自動送出，AC 8 的預覽是明訂的一步。
  //
  // 於 `useState` 的初始值判定而非 effect：這是從網址直接推導得出的，不需要先渲染一次
  // 空狀態再用 setState 補（`react-hooks/set-state-in-effect` 亦擋在 effect 內同步 setState）。
  const initialCode = searchParams.get("code") ?? ""
  const [joinOpen, setJoinOpen] = useState(initialCode !== "")

  const { data, isLoading, refetch } = useQuery({
    queryKey: QUERY_KEYS.etMyCourses.list(),
    queryFn: myCoursesApi.list,
  })

  const summary = data?.summary
  const courses = data?.courses ?? []

  /** 點擊課程卡片 → ET05 章節學習（AC 6；#255 接上，在此之前只給提示）。 */
  function openCourse(courseId: number) {
    navigate(`/et/courses/${courseId}/learn`)
  }

  function handleJoined(courseId: number, pendingOpen: boolean) {
    void refetch()
    if (pendingOpen) {
      // 課程尚未開放——導過去只會看到一個進不了的頁面，留在清單並說明原因（AC 4）。
      message.success("已加入，課程開放後將出現於清單")
      return
    }
    message.success("已加入課程")
    openCourse(courseId)
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
            <CourseCard course={course} onOpen={() => openCourse(course.course_id)} />
          </Grid>
        ))}
      </Grid>

      <JoinCourseDialog
        open={joinOpen}
        initialCode={initialCode}
        onClose={() => setJoinOpen(false)}
        onJoined={handleJoined}
        onAlreadyJoined={(courseId, pendingOpen, courseName) => {
          // 只送一則。`ET-5` 交付後這裡改成導向該課程（AC 10）。
          //
          // 帶課程名稱：學員可能是被標籤自動邀請帶進去的、從未輸入過邀請碼，
          // 只說「您已加入此課程」會讓人以為是剛才那次查詢把他加進去的。
          //
          // 未開放時**必須說明白**：光說「已加入」而清單是空的（AC 4），學員會以為
          // 系統壞了——實測就是這樣回報的。
          if (pendingOpen) {
            message.info(`您已加入「${courseName}」，將於課程開放後出現於清單`)
            return
          }
          // AC 10：不重複加入，**直接導向該課程**（#255 起目的地已存在）。
          openCourse(courseId)
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
