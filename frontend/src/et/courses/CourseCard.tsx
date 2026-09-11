import CalendarMonthIcon from "@mui/icons-material/CalendarMonth"
import FormatListNumberedIcon from "@mui/icons-material/FormatListNumbered"
import PeopleIcon from "@mui/icons-material/People"
import PersonIcon from "@mui/icons-material/Person"
import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardActionArea from "@mui/material/CardActionArea"
import Chip from "@mui/material/Chip"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import type { CourseCard as CourseCardData } from "./schemas"

const STATUS_LABEL: Record<CourseCardData["status"], { text: string; color: "default" | "success" | "warning" }> = {
  DRAFT: { text: "草稿", color: "default" },
  PUBLISHED: { text: "已發布", color: "success" },
  CLOSED: { text: "已關閉", color: "warning" },
}

/** `2026-04-15 09:00`；兩端都沒有時回 `—`（起訖為選填，草稿階段常是空的）。 */
function formatRange(start: string | null, end: string | null): string {
  const fmt = (iso: string | null) => {
    if (iso === null) return ""
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ""
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  const from = fmt(start)
  const to = fmt(end)
  if (!from && !to) return "—"
  return `${from || "—"} ～ ${to || "—"}`
}

/**
 * ET01 的一張課程卡片（`FR-ET-US7-03` / `-04`）。
 *
 * ## 「檢視」標籤由後端的 `is_owner` 決定
 *
 * **不在前端比對 `owner_id` 與當前使用者**——那等於把授權語意複製一份到瀏覽器，而兩份
 * 遲早分岔；分岔的表現是「卡片說可編輯、進去卻是唯讀」，使用者完全無從理解。
 *
 * ## 整張卡可點，且天生可聚焦
 *
 * 用 `CardActionArea` 而非在 `Card` 上掛 `onClick`：前者渲染成 `<button>`，鍵盤使用者
 * 按 Tab 就到得了。（#296 的表格得另外補一顆 `IconButton`，是因為 `<tr>` 不可聚焦。）
 */
export function CourseCard({ course, onOpen }: { course: CourseCardData; onOpen: (courseId: number) => void }) {
  const status = STATUS_LABEL[course.status]
  return (
    <Card variant="outlined" sx={{ height: "100%" }}>
      <CardActionArea onClick={() => onOpen(course.course_id)} sx={{ height: "100%", p: 2, alignItems: "stretch" }}>
        <Stack spacing={1} sx={{ height: "100%" }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
            <Chip size="small" color={status.color} label={status.text} />
            {/*
              他人課程的「檢視」標籤。**不可只用顏色或位置暗示**——它是唯一告訴使用者
              「點進去不能編輯」的線索，點進去才發現是唯讀會讓人以為系統壞了。
            */}
            {!course.is_owner && <Chip size="small" variant="outlined" label="檢視" />}
          </Stack>

          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {course.course_name}
          </Typography>

          {course.tags.length > 0 && (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {course.tags.map((tag) => (
                <Chip key={tag.tag_id} size="small" variant="outlined" label={tag.tag_name} />
              ))}
            </Stack>
          )}

          <Stack spacing={0.5} sx={{ color: "text.secondary", mt: "auto" }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Stack direction="row" spacing={0.5} alignItems="center">
                <PersonIcon fontSize="inherit" />
                <Typography variant="caption">
                  {course.owner_name ?? "—"}
                  {course.is_owner && "（您）"}
                </Typography>
              </Stack>
              <Stack direction="row" spacing={0.5} alignItems="center">
                <FormatListNumberedIcon fontSize="inherit" />
                <Typography variant="caption">{course.chapter_count} 章節</Typography>
              </Stack>
            </Stack>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <CalendarMonthIcon fontSize="inherit" />
              <Typography variant="caption">{formatRange(course.open_start_at, course.open_end_at)}</Typography>
            </Stack>
          </Stack>

          <Box sx={{ pt: 1, borderTop: 1, borderColor: "divider" }}>
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ color: "text.secondary" }}>
              <PeopleIcon fontSize="inherit" />
              {/* 在籍人數——已移除者不計入（後端已濾），問的是「現在有幾個人在上」 */}
              <Typography variant="caption">{course.student_count} 位學員</Typography>
            </Stack>
          </Box>
        </Stack>
      </CardActionArea>
    </Card>
  )
}
