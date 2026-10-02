import ChevronRightIcon from "@mui/icons-material/ChevronRight"
import Box from "@mui/material/Box"
import Chip from "@mui/material/Chip"
import Link from "@mui/material/Link"
import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useNavigate } from "react-router-dom"

import type { AdminCard, StudentCard, TeacherCard } from "./dashboardSchemas"
import { hasAdminData, hasStudentData, hasTeacherData } from "./dashboardSchemas"
import { useEtDashboard } from "./useEtDashboard"

/**
 * 單一數字格（數字 + 名稱）。**與 DM 概況的 `StatCard` 逐項一致**：外框、內距、置中、
 * `h4` 粗體數字、`Chip` 標籤。
 *
 * ⚠️ 刻意不設 `minWidth`（#475）——寬度一律交給外層 grid。原本設了 `minWidth: 110`
 * 並用 `Stack` 排，結果是四張小卡擠在左邊、右半邊整片空白，而 DM 那側是撐滿的。
 */
function StatCell({ label, count }: { label: string; count: number }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, textAlign: "center" }}>
      <Typography variant="h4" sx={{ fontWeight: 700 }}>
        {count}
      </Typography>
      <Chip size="small" label={label} sx={{ mt: 1 }} />
    </Paper>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
      {children}
    </Typography>
  )
}

function StudentBlock({ card }: { card: StudentCard }) {
  const navigate = useNavigate()
  return (
    <Box sx={{ mb: 3 }}>
      <SectionTitle>我的學習概況</SectionTitle>
      {/* 與 DM「各類型文件總數」同一組斷點：窄螢幕兩欄、md 以上四欄平均分配整個寬度 */}
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
          mb: 1,
        }}
      >
        <StatCell label="進行中" count={card.in_progress} />
        <StatCell label="未開始" count={card.not_started} />
        <StatCell label="已完成" count={card.completed} />
        <StatCell label="未開放" count={card.pending_open} />
      </Box>
      <Link component="button" variant="body2" onClick={() => navigate("/et/my-courses")}>
        前往我的課程
      </Link>
    </Box>
  )
}

function TeacherBlock({ card }: { card: TeacherCard }) {
  const navigate = useNavigate()
  return (
    <Box sx={{ mb: 3 }}>
      <SectionTitle>我的課程待辦</SectionTitle>
      {card.draft_count > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          有 <strong>{card.draft_count}</strong> 門課程尚未發布。
        </Typography>
      )}
      {card.ending_soon.length > 0 && (
        <List dense disablePadding>
          {card.ending_soon.map((line) => (
            <ListItemButton
              key={line.course_id}
              divider
              onClick={() => navigate(`/et/courses/${line.course_id}`)}
            >
              <ListItemText
                primary={
                  <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                    <Typography component="span" sx={{ fontWeight: 600 }}>
                      {line.course_name}
                    </Typography>
                    {/* 剩 0 天＝今天到期，用 error 與其他區分 */}
                    <Chip
                      size="small"
                      color={line.days_left === 0 ? "error" : "warning"}
                      label={line.days_left === 0 ? "今天到期" : `剩 ${line.days_left} 天`}
                    />
                  </Box>
                }
                secondary={`尚有 ${line.not_completed} 人未完課`}
              />
              <ChevronRightIcon color="disabled" />
            </ListItemButton>
          ))}
        </List>
      )}
    </Box>
  )
}

function AdminBlock({ card }: { card: AdminCard }) {
  return (
    <Box sx={{ mb: 3 }}>
      <SectionTitle>全體訓練概況</SectionTitle>
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: { xs: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
          mb: 1,
        }}
      >
        <StatCell label="逾期未完成" count={card.overdue_incomplete} />
      </Box>
      {card.by_course.length > 0 && (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            各課程完成率（低者在前）
          </Typography>
          <Stack spacing={0.5} sx={{ mb: 1 }}>
            {card.by_course.map((course) => (
              <Typography key={course.course_name} variant="body2">
                {course.course_name} {course.completion_rate}%
                <Typography component="span" variant="caption" color="text.secondary">
                  （{course.completed} / {course.enrolled} 人）
                </Typography>
              </Typography>
            ))}
          </Stack>
        </>
      )}
      {/* 全體完成率放小字：它不可行動，價值是「上面會問你這個數字」（評鑑、報告） */}
      <Typography variant="caption" color="text.secondary">
        全體訓練完成率 {card.completion_rate}%
      </Typography>
    </Box>
  )
}

/**
 * 中性歡迎頁之**教育訓練概況** widget（#453 / #89 的 P3）。
 *
 * ## 🔴 三張卡各依「**有無資料**」渲染，不是依角色
 *
 * #89 明訂：spec 定義「人人具 ET 學員預設角色」，若嚴格依角色顯示，**主管會看到一張
 * 空的「我的課程」**。判斷一律走 `hasStudentData` / `hasTeacherData` / `hasAdminData`，
 * ⛔ 不可改成 `modules.et.has_role && …`——DM 那側是那樣寫的，但它沒有「人人都有預設
 * 角色」這個前提。
 *
 * 排版順序 **管理者 → 教師 → 學員**（由廣到窄），對齊 #89 決策 3 的建議。
 *
 * 三張卡皆無資料時整個 widget 不渲染（不留一個空標題）。
 */
export function EtOverviewWidget({ enabled }: { enabled: boolean }) {
  const { data } = useEtDashboard(enabled)
  if (!data) return null

  const student = hasStudentData(data.student) ? data.student : null
  const teacher = hasTeacherData(data.teacher) ? data.teacher : null
  const admin = hasAdminData(data.admin) ? data.admin : null
  if (!student && !teacher && !admin) return null

  // 結構與 `DmOverviewWidget` 一致（#475）：**標題在白底卡之外、之上**，
  // 卡片用 `<Paper>`（非 `variant="outlined"`，與 DM 的陰影卡同款）。
  // 原本標題在 Paper 內、外層又是 outlined，兩個模組的區塊長得不一樣。
  return (
    <Box sx={{ mt: 4 }}>
      <Typography variant="h6" gutterBottom>
        ET 教育訓練概況
      </Typography>
      <Paper sx={{ p: 2, mb: 3 }}>
        {admin && <AdminBlock card={admin} />}
        {teacher && <TeacherBlock card={teacher} />}
        {student && <StudentBlock card={student} />}
      </Paper>
    </Box>
  )
}
