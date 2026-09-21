import ExpandMoreIcon from "@mui/icons-material/ExpandMore"
import RestartAltIcon from "@mui/icons-material/RestartAlt"
import Accordion from "@mui/material/Accordion"
import AccordionDetails from "@mui/material/AccordionDetails"
import AccordionSummary from "@mui/material/AccordionSummary"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import LinearProgress from "@mui/material/LinearProgress"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Tooltip from "@mui/material/Tooltip"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { BlockHeading } from "./BlockHeading"
import { studentsApi } from "./studentsService"
import type { TeacherQuizRow } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"

/** 停用「重置」時說明**為什麼**——三種原因對教師的意義完全不同。 */
function resetDisabledReason(quiz: TeacherQuizRow, readOnly: boolean): string {
  if (readOnly) return "課程已關閉，無法重置"
  if (quiz.attempts.length === 0) return "尚未作答，配額原本就是滿的"
  if (quiz.is_passed) return "已及格，重置沒有意義"
  return `尚有 ${quiz.max_retry + 1 - quiz.used_attempts} 次可作答，學員自己還能重考`
}

/**
 * ET03 區塊 2：作答明細（`FR-ET-US9-04` / `-05`）。
 *
 * ## 三層展開：學員 → 各測驗之歷次 attempt → 單次逐題明細
 *
 * 用 `Accordion` 而非自刻展開——它原生可聚焦、帶 `aria-expanded`，鍵盤與螢幕閱讀器都能用。
 *
 * ## 未作答的測驗**仍要列出**
 *
 * `attempts` 為空時顯示「尚未作答」（ET-MSG-ET03-005）。整個測驗不出現的話，教師分不出
 * 「他沒考」與「這門課沒這個測驗」。
 *
 * ## `can_reset` 由後端給，前端不自行推導
 *
 * 規則是「次數用盡（`used > max_retry`，總配額為 `max_retry + 1`）且未及格且曾作答」。
 * 在前端複製一份遲早分岔——而分岔的表現是按鈕可點、按下去卻 409。
 */
export function AttemptOverviewBlock({
  courseId,
  readOnly,
  onOpenDetail,
  onReset,
}: {
  courseId: number
  readOnly: boolean
  onOpenDetail: (attemptId: number) => void
  onReset: (userId: string, userName: string | null, quiz: TeacherQuizRow) => void
}) {
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEYS.etStudents.attemptOverview(courseId),
    queryFn: () => studentsApi.attemptOverview(courseId),
  })

  const students = data?.students ?? []

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <BlockHeading
        title="作答明細"
        note="一次列出所有已作答學員；點學員展開其歷次作答與逐題明細"
      />

      {isError && <Typography color="error">作答明細載入失敗</Typography>}
      {isPending && <LinearProgress sx={{ mt: 1 }} />}

      {!isPending && !isError && students.length === 0 && (
        <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          此課程尚無學員作答
        </Typography>
      )}

      <Stack sx={{ mt: 1 }}>
        {students.map((student) => (
          <Accordion key={student.user_id} disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>{student.user_name ?? "—"}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {student.quizzes.map((quiz) => (
                <Stack key={quiz.quiz_id} spacing={1} sx={{ mb: 3 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" useFlexGap>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="subtitle2">{quiz.quiz_name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        已用 {quiz.used_attempts} / {quiz.max_retry + 1} 次
                      </Typography>
                      {quiz.is_passed && <Chip size="small" color="success" label="已及格" />}
                    </Stack>
                    <Tooltip title={quiz.can_reset ? "重置後該學員可再作答" : resetDisabledReason(quiz, readOnly)}>
                      {/* span 包住：disabled 的按鈕不觸發事件，Tooltip 會失效 */}
                      <span>
                        <Button
                          size="small"
                          startIcon={<RestartAltIcon />}
                          disabled={!quiz.can_reset || readOnly}
                          onClick={() => onReset(student.user_id, student.user_name, quiz)}
                        >
                          重置重考次數
                        </Button>
                      </span>
                    </Tooltip>
                  </Stack>

                  {quiz.attempts.length === 0 ? (
                    /* ET-MSG-ET03-005：該測驗仍要列出，只是標示尚未作答 */
                    <Typography variant="body2" color="text.secondary">
                      尚未作答
                    </Typography>
                  ) : (
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>次別</TableCell>
                          <TableCell>作答時間</TableCell>
                          <TableCell align="right">分數</TableCell>
                          <TableCell>是否及格</TableCell>
                          <TableCell>明細</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {quiz.attempts.map((attempt) => (
                          <TableRow
                            key={attempt.attempt_id}
                            hover
                            sx={{ cursor: "pointer" }}
                            onClick={() => onOpenDetail(attempt.attempt_id)}
                          >
                            <TableCell>第 {attempt.attempt_no} 次</TableCell>
                            <TableCell>{new Date(attempt.submitted_at).toLocaleString("zh-TW")}</TableCell>
                            {/* 分母用快照的 points_total，**不可寫死 100**——發布後教師仍可改配分 */}
                            <TableCell align="right">
                              {attempt.score} / {attempt.points_total}
                            </TableCell>
                            <TableCell>
                              <Chip
                                size="small"
                                color={attempt.is_pass ? "success" : "default"}
                                label={attempt.is_pass ? "及格" : "未及格"}
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption" color="text.secondary">
                                查看逐題明細
                              </Typography>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </Stack>
              ))}
            </AccordionDetails>
          </Accordion>
        ))}
      </Stack>
    </Paper>
  )
}
