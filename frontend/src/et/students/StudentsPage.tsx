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
import { PendingInviteBlock } from "./PendingInviteBlock"
import { downloadStudentsCsv, downloadSurveyCsv, studentsApi } from "./studentsService"
import type { PendingInviteRow, StudentRow, TeacherQuizRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { coursesApi } from "../courses/coursesService"

/** 待確認的操作——兩者都需要二次確認，且文案本身就是規格（ET-MSG-ET03-001 / -003）。 */
type Pending =
  | { kind: "reset"; userId: string; userName: string | null; quiz: TeacherQuizRow }
  | { kind: "remove"; student: StudentRow }
  | { kind: "resend"; invite: PendingInviteRow }
  | { kind: "revoke"; invite: PendingInviteRow }

/** 四種確認框的標題。集中於此，新增動作時不會漏掉標題而沿用上一個。 */
const DIALOG_TITLE: Record<Pending["kind"], string> = {
  reset: "重置重考次數",
  remove: "移除學員",
  resend: "再次寄送邀請",
  revoke: "撤回邀請",
}

/**
 * 移除確認框的文案——**作答中與否是兩則不同的訊息**。
 *
 * 🔴 `ET-MSG-ET03-003`（警告版）只在該學員手上有未提交的 attempt 時出現。原先兩種
 * 情況合用一句「該學員**若**正在作答……」，把警告稀釋成每次都出現的免責聲明——
 * 而每次都出現的警告等於沒有警告，真正該停下來看的那次也會被一起略過。
 */
/** 四種動作的確認文案。`remove` 的警告版由呼叫端另以 `<Alert>` 呈現。 */
function confirmMessage(pending: Pending | null): string {
  if (pending === null) return ""
  switch (pending.kind) {
    case "reset":
      // ET-MSG-ET03-001
      return `確定重置 ${pending.userName ?? "該學員"} 於「${pending.quiz.quiz_name}」之重考次數？歷次作答明細仍會完整保留。`
    case "resend":
      // 🔴「原連結將失效」必須講——重寄會換新 token，受邀者手上的舊信隨即作廢。
      // 不講的話，教師會以為只是「再提醒一次」，而對方點舊信會看到「連結無效」。
      return `確定重新寄送邀請信至 ${pending.invite.email}？原邀請連結將失效，對方須改用新信中的連結。`
    case "revoke":
      // ET-MSG-ET03-102。「原邀請連結將失效」是規格文案，不可簡化。
      return `確定撤回對 ${pending.invite.email} 的邀請？原邀請連結將失效。`
    default:
      return removeMessage(pending)
  }
}

function removeMessage(pending: Pending | null): string {
  if (pending?.kind !== "remove") return ""
  const name = pending.student.user_name ?? "該學員"
  return pending.student.has_in_progress_attempt
    ? `${name}作答中，移除後其當前作答將保留並計入歷史。確定移除？`
    : `確定移除 ${name}？學習歷史完整保留。`
}

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

  /** 寫入成功後一次失效該課程的三個區塊。用 `QUERY_KEYS` 的前綴而非裸字面值——
      後者不會跟著 key 結構改動，會安靜地算錯失效範圍。 */
  const invalidateAll = (id: number) => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEYS.etStudents.all(id) })
  }

  const confirm = async () => {
    if (pending === null || courseId === "") return
    setBusy(true)
    try {
      if (pending.kind === "reset") {
        await studentsApi.resetRetry(courseId, pending.userId, pending.quiz.quiz_id)
        notify.message.success("已重置重考次數")
      } else if (pending.kind === "remove") {
        await studentsApi.removeStudent(courseId, pending.student.user_id)
        notify.message.success("已移除學員")
      } else if (pending.kind === "resend") {
        await studentsApi.resendInvite(pending.invite.invitation_id)
        notify.message.success("邀請信已重新寄出")
      } else {
        await studentsApi.revokeInvite(pending.invite.invitation_id)
        notify.message.success("邀請已撤回")
      }
      invalidateAll(courseId)
      setPending(null)
    } catch (err) {
      // 🔴 破壞性動作失敗**必須看得見**。少了這段，403 / 409（不符重置條件、課程已
      // 關閉）/ 404（清單已過期）/ 429 全部靜默——教師看到的是「按了沒反應」，而
      // 確認框還留在原地，他會再按一次。
      //
      // 刻意**不關閉確認框**：讓教師看著同一個對話框讀到失敗原因，比把它關掉再彈一則
      // Snackbar 更容易把因果連起來。
      notify.message.error(toApiError(err).errorMessage)
    } finally {
      setBusy(false)
    }
  }

  /** 兩支 CSV 共用——匯出走 axios blob，成功與失敗都要看得見。 */
  const exportCsv = async (kind: "students" | "survey") => {
    if (courseId === "") return
    try {
      await (kind === "students" ? downloadStudentsCsv(courseId) : downloadSurveyCsv(courseId))
      // ET-MSG-ET03-007。瀏覽器下載是**無聲**的：檔案落到下載資料夾、頁面完全沒變化。
      // 少了這則，教師按下匯出後唯一的回饋是「什麼都沒發生」，於是再按一次。
      notify.message.success("CSV 已匯出")
    } catch (err) {
      notify.message.error(toApiError(err).errorMessage)
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
        <PendingInviteBlock
          courseId={courseId}
          readOnly={readOnly}
          onResend={(invite) => setPending({ kind: "resend", invite })}
          onRevoke={(invite) => setPending({ kind: "revoke", invite })}
        />
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
            onExport={() => void exportCsv("students")}
          />
          <AttemptOverviewBlock
            courseId={courseId}
            readOnly={readOnly}
            onOpenDetail={setAttemptId}
            onReset={(userId, userName, quiz) => setPending({ kind: "reset", userId, userName, quiz })}
          />
          <SurveyResultBlock courseId={courseId} onExport={() => void exportCsv("survey")} />
        </>
      )}

      <TeacherAttemptDialog attemptId={attemptId} onClose={() => setAttemptId(null)} />

      <Dialog open={pending !== null} onClose={() => !busy && setPending(null)}>
        {/* `pending` 為 null 是關閉動畫期間——給空字串，不要 fallback 到某個動作的
            標題，否則每次關閉都會閃一下「移除學員」。 */}
        <DialogTitle>{pending === null ? "" : DIALOG_TITLE[pending.kind]}</DialogTitle>
        <DialogContent>
          {pending?.kind === "remove" && pending.student.has_in_progress_attempt ? (
            /* ET-MSG-ET03-003 為「警告」型訊息——用 Alert 而非純文字，
               否則它與一般確認長得一模一樣，等於沒有分級。 */
            <Alert severity="warning">{removeMessage(pending)}</Alert>
          ) : (
            <DialogContentText>{confirmMessage(pending)}</DialogContentText>
          )}
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
