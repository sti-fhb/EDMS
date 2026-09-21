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
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { AttemptOverviewBlock } from "./AttemptOverviewBlock"
import { StudentListBlock } from "./StudentListBlock"
import { SurveyResultBlock } from "./SurveyResultBlock"
import { TeacherAttemptDialog } from "./TeacherAttemptDialog"
import { downloadStudentsCsv, downloadSurveyCsv, studentsApi } from "./studentsService"
import type { ApprovalResult, ApproveResult, SkipReason, StudentRow, TeacherQuizRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { coursesApi } from "../courses/coursesService"

/** 待確認的操作——全部需要二次確認，且文案本身就是規格（ET-MSG-ET03-001 / -003 / -301 …）。 */
type Pending =
  | { kind: "reset"; userId: string; userName: string | null; quiz: TeacherQuizRow }
  | { kind: "remove"; student: StudentRow }
  /** US16 核可（單筆即 `students` 長度為 1）。 */
  | { kind: "approve"; students: StudentRow[]; result: ApprovalResult }
  /**
   * US16 撤銷核可。
   *
   * 命名保留 `revokeApproval` 而不簡化為 `revoke`：#362 之前另有一個 `revoke`（撤回
   * 邀請），兩者曾經並存且是完全不同的動作。改名會讓日後讀 git 歷史的人把兩者混為一談。
   */
  | { kind: "revokeApproval"; student: StudentRow }

/** 四種確認框的標題。集中於此，新增動作時不會漏掉標題而沿用上一個。 */
const DIALOG_TITLE: Record<Pending["kind"], string> = {
  reset: "重置重考次數",
  remove: "移除學員",
  approve: "線下核可",
  revokeApproval: "撤銷核可",
}

/** 三種跳過理由對應的提示。`NOT_COMPLETED` 的文案依筆數分流，故不在此表。 */
const SKIP_LABEL: Record<SkipReason, string> = {
  NOT_COMPLETED: "尚未完課",
  ALREADY_APPROVED: "已有核可紀錄",
  NOT_ENROLLED: "已不在此課程",
}

/**
 * 把核可結果翻成給教師看的一句話（`ET-MSG-ET03-302` / `-303` / `-304` / `-309`）。
 *
 * 🔴 **`approved === 0` 也是 HTTP 200**——後端讓單筆與批次走同一條路徑，全部被跳過時
 * 不回錯誤。只看狀態碼就報「已完成核可」會讓教師以為寫進去了。
 *
 * 單筆與批次的訊息**型別不同**：spec 把 `304`（單筆未完課）列為**錯誤**、`303`（批次
 * 含未完課）列為**提示**。同一件事在兩種情境下的嚴重度不同——批次跳過一兩個人是預期
 * 中的，單獨對一個人按「通過」卻沒寫進去則是操作失敗。
 */
function approveOutcome(
  result: ApproveResult,
  requested: number,
): { severity: "success" | "warning" | "error"; text: string } {
  if (result.skipped.length === 0) {
    return { severity: "success", text: "已完成核可" } // ET-MSG-ET03-302
  }
  if (requested === 1) {
    const reason = result.skipped[0].reason
    // ET-MSG-ET03-304（未完課）／-309（已有核可紀錄）
    return {
      severity: "error",
      text: reason === "NOT_COMPLETED" ? "學員尚未完課，無法核可" : `無法核可：${SKIP_LABEL[reason]}`,
    }
  }
  // 批次：逐理由聚合，讓教師知道各要做什麼（等他完課 vs 先撤銷）
  const counts = new Map<SkipReason, number>()
  for (const item of result.skipped) counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1)
  const detail = [...counts].map(([reason, n]) => `${SKIP_LABEL[reason]}（${n} 筆）`).join("、")
  return {
    severity: result.approved > 0 ? "warning" : "error",
    text: `已核可 ${result.approved} 筆；已跳過：${detail}`, // ET-MSG-ET03-303 / -309
  }
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
    case "approve": {
      // ET-MSG-ET03-301。批次帶筆數——教師勾了 12 個人卻只看到「確定核可所選學員？」
      // 時，無從察覺自己少勾或多勾了。
      const who =
        pending.students.length === 1
          ? (pending.students[0].user_name ?? "該學員")
          : `所選 ${pending.students.length} 位學員`
      const verdict = pending.result === "PASS" ? "通過" : "不通過"
      const mail = pending.result === "PASS" ? "核可後系統將寄送通知信給學員。" : "不通過不寄送通知信。"
      return `確定核可${who}為「${verdict}」？${mail}`
    }
    case "revokeApproval":
      return `確定撤銷 ${pending.student.user_name ?? "該學員"} 的核可？撤銷後回到「待核可」，之後仍可重新核可。`
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
 * ①已加入學員 ②作答明細 ③問卷結果。
 *
 * 原本上方還有「已加入 / 待加入」兩個 tab，`待加入` 於 #362 隨 `ET_INVITATION` 一併
 * 移除——Email 邀請現在寄出即加入，被邀請的人直接出現在①，沒有第二個清單可看。單剩
 * 一個 tab 沒有意義，故整組 `<Tabs>` 也移除。
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
  const [attemptId, setAttemptId] = useState<number | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  /** 核可備註（不通過用，選填）與撤銷原因（必填）共用——兩者不會同時出現。 */
  const [noteInput, setNoteInput] = useState("")
  /** 撤銷原因為空時的 inline 錯誤（`ET-MSG-ET03-305`）。 */
  const [reasonError, setReasonError] = useState(false)

  /** 開啟確認框時一併清掉上一次的輸入——留著會讓下一次撤銷帶上別人的原因。 */
  const openPending = (next: Pending) => {
    setNoteInput("")
    setReasonError(false)
    setPending(next)
  }
  const closePending = () => {
    setPending(null)
    setNoteInput("")
    setReasonError(false)
  }

  // 課程下拉取自 ET01 的清單（`scope=mine`）——教師只能追蹤自己建立的課程，
  // 與後端 `ensure_owner` 一致；列出他人課程只會產生「選了必定 403」的選項。
  const listParams = useMemo(() => ({ scope: "mine" as const, page: 1, limit: 100 }), [])
  const { data: courses } = useQuery({
    queryKey: QUERY_KEYS.etCourses.list(listParams),
    queryFn: () => coursesApi.list(listParams),
  })

  // #359 第 4 項：**排除草稿**。草稿課程於發布時才帶入學員，選了只會看到三個空區塊，
  // 而畫面不會說明為什麼——教師會以為壞掉。
  //
  // 過濾放前端（2026-09-18 使用者裁示）：ET01 的清單本身沒有錯，草稿是它該有的內容；
  // 錯的是 ET03 對同一份清單的需求不同。改後端等於為單一消費者多開一個 `scope`。
  //
  // ⚠️ **已關閉課程必須保留**——ET-11 AC 10：關閉後仍可閱覽學員清單、作答明細與問卷
  // 結果，只是不可再重置／移除。只排除 `DRAFT`，不要用 `is_closed` 或 `status !== "PUBLISHED"`。
  const options = (courses?.data ?? []).filter((c) => c.status !== "DRAFT")
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
    // 🔴 撤銷原因必填**擋在送出之前**（`ET-MSG-ET03-305`）：inline 錯誤掛在那個輸入框
    // 上，比送出後收一則 Snackbar 更容易讓教師知道要補什麼。後端仍會擋（422），這裡
    // 只是不讓他白跑一趟。
    if (pending.kind === "revokeApproval" && noteInput.trim() === "") {
      setReasonError(true)
      return
    }
    setBusy(true)
    try {
      if (pending.kind === "reset") {
        await studentsApi.resetRetry(courseId, pending.userId, pending.quiz.quiz_id)
        notify.message.success("已重置重考次數")
      } else if (pending.kind === "remove") {
        await studentsApi.removeStudent(courseId, pending.student.user_id)
        notify.message.success("已移除學員")
      } else if (pending.kind === "approve") {
        const outcome = await studentsApi.approve(
          courseId,
          pending.students.map((s) => s.user_id),
          pending.result,
          // 備註只在「不通過」時送——`FR-ET-US16-04` 明訂 FAIL 得附備註，
          // 通過的確認框不顯示該欄位，送出空字串只會在 DB 留一堆空備註。
          pending.result === "FAIL" ? noteInput.trim() || undefined : undefined,
        )
        const { severity, text } = approveOutcome(outcome, pending.students.length)
        notify.message[severity](text)
      } else {
        // `approval_version` 在有核可紀錄時必為數字；撤銷鈕只對已有結果的列顯示。
        await studentsApi.revokeApproval(
          courseId,
          pending.student.user_id,
          noteInput.trim(),
          pending.student.approval_version ?? 0,
        )
        notify.message.success("已撤銷核可") // ET-MSG-ET03-306
      }
      invalidateAll(courseId)
      closePending()
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

      {courseId === "" ? (
        <Alert severity="info">請先於右上選擇要檢視的課程。</Alert>
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
            onRemove={(student) => openPending({ kind: "remove", student })}
            onExport={() => void exportCsv("students")}
            onApprove={(students, result) =>
              openPending(
                result === null
                  ? { kind: "revokeApproval", student: students[0] }
                  : { kind: "approve", students, result },
              )
            }
          />
          <AttemptOverviewBlock
            courseId={courseId}
            readOnly={readOnly}
            onOpenDetail={setAttemptId}
            onReset={(userId, userName, quiz) => openPending({ kind: "reset", userId, userName, quiz })}
          />
          <SurveyResultBlock courseId={courseId} onExport={() => void exportCsv("survey")} />
        </>
      )}

      <TeacherAttemptDialog attemptId={attemptId} onClose={() => setAttemptId(null)} />

      <Dialog open={pending !== null} onClose={() => !busy && closePending()} fullWidth maxWidth="xs">
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

          {/* 不通過可附備註（`FR-ET-US16-04`），**選填** */}
          {pending?.kind === "approve" && pending.result === "FAIL" && (
            <TextField
              fullWidth
              multiline
              minRows={2}
              size="small"
              sx={{ mt: 2 }}
              label="備註（選填）"
              placeholder="例：實機操作未達標準"
              value={noteInput}
              onChange={(e) => setNoteInput(e.target.value)}
            />
          )}

          {/* 撤銷原因**必填**（`FR-ET-US16-06`）。錯誤以 helperText 掛在欄位上而非
              Snackbar——錯誤就在這個輸入框，訊息飄到畫面角落等於要教師自己連連看。 */}
          {pending?.kind === "revokeApproval" && (
            <TextField
              required
              fullWidth
              multiline
              minRows={2}
              size="small"
              sx={{ mt: 2 }}
              label="撤銷原因"
              placeholder="例：考核紀錄登錄錯誤"
              value={noteInput}
              error={reasonError}
              helperText={reasonError ? "請填寫撤銷原因" : "此原因會寫入稽核紀錄"}
              onChange={(e) => {
                setNoteInput(e.target.value)
                if (reasonError) setReasonError(false)
              }}
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={closePending} disabled={busy}>
            取消
          </Button>
          <Button
            onClick={confirm}
            disabled={busy}
            color={
              pending?.kind === "remove" || (pending?.kind === "approve" && pending.result === "FAIL")
                ? "error"
                : "primary"
            }
            variant="contained"
          >
            確定
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
