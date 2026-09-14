import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { AttemptOverviewBlock } from "./AttemptOverviewBlock"
import { StudentListBlock } from "./StudentListBlock"
import { SurveyResultBlock } from "./SurveyResultBlock"
import { TeacherAttemptDialog } from "./TeacherAttemptDialog"
import { studentsApi } from "./studentsService"
import type { StudentRow, TeacherQuizRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { coursesApi } from "../courses/coursesService"

/** 待確認的操作——兩者都需要二次確認，且文案本身就是規格（ET-MSG-ET03-001 / -003）。 */
type Pending =
  | { kind: "reset"; userId: string; userName: string | null; quiz: TeacherQuizRow }
  | { kind: "remove"; student: StudentRow }

/**
 * ET03 學員學習狀況追蹤（US9 / #322）。
 *
 * ## 「已加入」頁籤 = 一個課程的完整資料視圖，分三區塊
 *
 * ①已加入學員 ②作答明細 ③問卷結果。「待加入」tab 屬 `ET-12`，本 issue 只放佔位。
 *
 * ## 課程已關閉時只停**寫入**
 *
 * 三區塊照常閱覽、照常匯出 CSV（AC 10 / #255 裁示 Q2=A「讀照舊、寫全停」），只有
 * 「重置重考次數」與「移除學員」禁用。
 *
 * 🔴 **停用時必須說明原因**：ET-16（到期自動轉 `CLOSED`）未實作，所以期間已過的課程
 * **狀態欄仍寫著「已發布」**。教師會看到一門標著「已發布」的課程、管理按鈕卻全部禁用
 * ——不說明的話，那在教師眼中是「系統壞了」或「我的權限被拿掉了」。常駐 Alert 同時回答
 * 「為什麼不能點」與「要怎樣才能點」。
 */
export function EtStudentsPage() {
  const notify = useNotification()
  const queryClient = useQueryClient()
  const [courseId, setCourseId] = useState<number | "">("")
  const [tab, setTab] = useState<"joined" | "pending">("joined")
  const [attemptId, setAttemptId] = useState<number | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)

  // 課程下拉取自 ET01 的清單（`scope=mine`）——教師只能追蹤自己建立的課程，
  // 與後端 `ensure_owner` 一致；列出他人課程只會產生「選了必定 403」的選項。
  const listParams = useMemo(() => ({ scope: "mine" as const, page: 1, limit: 100 }), [])
  const { data: courses } = useQuery({
    queryKey: QUERY_KEYS.etCourses.list(listParams),
    queryFn: () => coursesApi.list(listParams),
  })

  const options = courses?.data ?? []
  const selected = options.find((c) => c.course_id === courseId)
  // 由後端算好的 `is_closed`——**不自己判 `status`**：期間已過時 status 仍是 PUBLISHED
  const readOnly = selected?.is_closed ?? false

  const invalidateAll = (id: number) => {
    queryClient.invalidateQueries({ queryKey: ["et", "tracking", id] })
  }

  const confirm = async () => {
    if (pending === null || courseId === "") return
    setBusy(true)
    try {
      if (pending.kind === "reset") {
        await studentsApi.resetRetry(courseId, pending.userId, pending.quiz.quiz_id)
        notify.message.success("已重置重考次數")
      } else {
        await studentsApi.removeStudent(courseId, pending.student.user_id)
        notify.message.success("已移除學員")
      }
      invalidateAll(courseId)
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        <Typography variant="h5">學員</Typography>
        <TextField
          select
          size="small"
          label="課程"
          sx={{ minWidth: 260 }}
          value={courseId}
          onChange={(e) => setCourseId(e.target.value === "" ? "" : Number(e.target.value))}
        >
          <MenuItem value="">請選擇課程</MenuItem>
          {options.map((c) => (
            <MenuItem key={c.course_id} value={c.course_id}>
              {c.course_name}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Tabs value={tab} onChange={(_, v: "joined" | "pending") => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="joined" label="已加入" />
        <Tab value="pending" label="待加入" />
      </Tabs>

      {courseId === "" ? (
        <Alert severity="info">請先於右上選擇要檢視的課程。</Alert>
      ) : tab === "pending" ? (
        <Alert severity="info">「待加入」邀請追蹤屬 ET-12，尚未實作。</Alert>
      ) : (
        <>
          {readOnly && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              此課程已結束閱課期間，目前為<strong>唯讀</strong>：仍可閱覽三區塊與匯出 CSV，
              但不可重置重考次數或移除學員。如需管理學員，請先於課程編輯頁執行<strong>再開課</strong>。
            </Alert>
          )}

          <StudentListBlock
            courseId={courseId}
            readOnly={readOnly}
            onRemove={(student) => setPending({ kind: "remove", student })}
          />
          <AttemptOverviewBlock
            courseId={courseId}
            readOnly={readOnly}
            onOpenDetail={setAttemptId}
            onReset={(userId, userName, quiz) => setPending({ kind: "reset", userId, userName, quiz })}
          />
          <SurveyResultBlock courseId={courseId} />
        </>
      )}

      <TeacherAttemptDialog attemptId={attemptId} onClose={() => setAttemptId(null)} />

      <Dialog open={pending !== null} onClose={() => !busy && setPending(null)}>
        <DialogTitle>{pending?.kind === "reset" ? "重置重考次數" : "移除學員"}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {pending?.kind === "reset"
              ? /* ET-MSG-ET03-001 */
                `確定重置 ${pending.userName ?? "該學員"} 於「${pending.quiz.quiz_name}」之重考次數？歷次作答明細仍會完整保留。`
              : /* ET-MSG-ET03-003：作答中的警告文案本身就是規格，不可簡化 */
                `確定移除 ${pending?.kind === "remove" ? (pending.student.user_name ?? "該學員") : ""}？該學員若正在作答，其當前作答將保留並計入歷史；學習歷史完整保留。`}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)} disabled={busy}>
            取消
          </Button>
          <Button
            onClick={confirm}
            disabled={busy}
            color={pending?.kind === "remove" ? "error" : "primary"}
            variant="contained"
          >
            確定
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
