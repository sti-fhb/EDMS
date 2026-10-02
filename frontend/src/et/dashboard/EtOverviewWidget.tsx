import ChevronRightIcon from "@mui/icons-material/ChevronRight"
import Box from "@mui/material/Box"
import Chip from "@mui/material/Chip"
import Divider from "@mui/material/Divider"
import Link from "@mui/material/Link"
import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
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

/**
 * 區塊標題。**與 DM 的「最新更新公告」同款**：`subtitle1` 粗體 + 行內 `caption` 註記
 * + 下方分隔線（2026-10-02 手測裁示）。
 *
 * `note` 走 `component="span"` 掛在同一個 `Typography` 裡而不是另起一行——那正是 DM
 * 「（近一個月發布）」的寫法，標題與註記共用基線才不會看起來像兩層標題。
 *
 * ⚠️ 標題文字另包一層 `<span>`（無任何樣式、不影響外觀）：外層 `Typography` 的
 * `textContent` 是「標題 + 註記」，`getByText("全體訓練概況")` 這種精確查詢會落空。
 * 包起來之後標題本身有自己的節點，測試與螢幕閱讀器都抓得到。
 */
function SectionTitle({ children, note }: { children: React.ReactNode; note?: string }) {
  return (
    <>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        <Box component="span">{children}</Box>
        {note !== undefined && (
          <Typography component="span" variant="caption" color="text.secondary">
            {" "}
            {note}
          </Typography>
        )}
      </Typography>
      <Divider sx={{ mb: 1.5 }} />
    </>
  )
}

/**
 * 顯示用的整數百分比。**無條件捨去，不是四捨五入。**
 *
 * 🔴 `99.6%` 四捨五入成 `100%` 會讓管理者以為那門課全部完訓、停止催辦；捨去成 `99%`
 * 不會往樂觀的方向騙人。真正到 100%（如 `100.00`）捨去後仍是 100，不受影響。
 *
 * 另一個方向（`0.4%` → `0%`）可接受：表格同列的「完成 1 / 250 人」本來就是精確值。
 *
 * 回 `null` 代表解析不出數字——此時畫 `—` 而非 `0%`。⚠️ **不可退化成 0**：那是一個
 * 看起來完全合理、卻與事實無關的數字，沒有人會發現它壞了。
 */
function wholePercent(rate: string): number | null {
  const parsed = Number(rate)
  return Number.isFinite(parsed) ? Math.floor(parsed) : null
}

function PercentText({ rate }: { rate: string }) {
  const whole = wholePercent(rate)
  return <>{whole === null ? "—" : `${whole}%`}</>
}

function StudentBlock({ card }: { card: StudentCard }) {
  const navigate = useNavigate()
  return (
    <Paper sx={{ p: 2, mb: 3 }}>
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
    </Paper>
  )
}

function TeacherBlock({ card }: { card: TeacherCard }) {
  const navigate = useNavigate()
  return (
    <Paper sx={{ p: 2, mb: 3 }}>
      <SectionTitle>我的課程待辦</SectionTitle>
      {card.draft_count > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          有 <strong>{card.draft_count}</strong> 門課程尚未發布。
        </Typography>
      )}
      {card.ending_soon.length > 0 && (
        <List dense disablePadding>
          {card.ending_soon.map((line) => (
            <ListItemButton key={line.course_id} divider onClick={() => navigate(`/et/courses/${line.course_id}`)}>
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
    </Paper>
  )
}

/**
 * 管理者卡「全體訓練概況」。
 *
 * ## 為什麼是表格（2026-10-02 手測裁示）
 *
 * 改版前每一列是一句跑完的文字（`採血教學 0.00%（0 / 1 人）`），眼睛沒辦法往下掃同一欄
 * 比大小——而管理者看這張卡就是要找「哪一門落後」。表格把完成率對齊成一欄，順便解決
 * 「資料全擠在左邊」：改版前上方是一個 `repeat(4, 1fr)` 的 grid 裡只放**一格**
 * （逾期未完成），它佔 1/4、右邊 3/4 整片空白。
 *
 * ⚠️ **目前全列、不截斷。** 課程數成長後這張卡會愈來愈長，屆時若要只列前 N 門，
 * **必須在畫面上寫明**（例如「完成率最低的 5 門」）——否則管理者會以為那就是全部課程，
 * 而那是一個看起來完全正常的誤解。現階段課程少，全列沒問題。
 */
function AdminBlock({ card }: { card: AdminCard }) {
  return (
    <Paper sx={{ p: 2, mb: 3 }}>
      <SectionTitle note="各課程完成率">全體訓練概況</SectionTitle>
      <TableContainer>
        <Table size="small" aria-label="各課程完成率">
          <TableHead>
            <TableRow>
              <TableCell>課程</TableCell>
              <TableCell align="right">完成</TableCell>
              <TableCell align="right">完成率</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {/* key 用 `course_id`：同名課程（不同年度的年度訓練）後端刻意不合併 */}
            {card.by_course.map((course) => (
              <TableRow key={course.course_id}>
                <TableCell>
                  <Typography variant="body1" sx={{ fontWeight: 600 }}>
                    {course.course_name}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  {course.completed} / {course.enrolled} 人
                </TableCell>
                <TableCell align="right">
                  <PercentText rate={course.completion_rate} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {/* 比照 DM「總計 N 份」：聚合值放右下小字，不佔表格的一列 */}
      <Typography variant="body2" color="text.secondary" sx={{ textAlign: "right", mt: 2 }}>
        全體訓練完成率 <PercentText rate={card.completion_rate} />
      </Typography>
    </Paper>
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
 * ## 三塊各自一張白底卡（2026-10-02 手測裁示）
 *
 * 比照 DM 的「各類型文件總數」與「最新更新公告」——一個區塊一張 `Paper`。三塊共用一張
 * 時，`我的學習概況` 的四格數字與 `全體訓練概況` 的表格之間沒有任何視覺分界，讀起來
 * 像同一組資料的續篇。
 *
 * ⚠️ 每張都帶 `mb: 3`（含最後一張），不做「最後一張不留下邊距」的處理：**哪一張是
 * 最後一張隨角色而變**，條件式邊距會在某些角色組合下漏掉。多出來的下邊距也剛好隔開
 * 緊接在後的 DM widget。
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

  return (
    <Box sx={{ mt: 4 }}>
      <Typography variant="h6" gutterBottom>
        ET 教育訓練概況
      </Typography>
      {admin && <AdminBlock card={admin} />}
      {teacher && <TeacherBlock card={teacher} />}
      {student && <StudentBlock card={student} />}
    </Box>
  )
}
