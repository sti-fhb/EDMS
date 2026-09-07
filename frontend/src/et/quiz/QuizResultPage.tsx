import ReplayIcon from "@mui/icons-material/Replay"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Typography from "@mui/material/Typography"
import { useLocation, useNavigate } from "react-router-dom"

import type { AttemptResult, QuestionResult } from "./attemptSchemas"

const OUTCOME_LABEL: Record<QuestionResult["outcome"], { text: string; color: "success" | "warning" | "error" }> = {
  CORRECT: { text: "答對", color: "success" },
  PARTIAL: { text: "部分對", color: "warning" },
  WRONG: { text: "答錯", color: "error" },
}

/** 逗號分隔的選項文字；空選擇顯示「未作答」而非空白（空白看起來像壞掉）。 */
function optionText(options: QuestionResult["options"], predicate: (o: QuestionResult["options"][number]) => boolean) {
  const picked = options.filter(predicate).map((o) => o.text)
  return picked.length > 0 ? picked.join("、") : "未作答"
}

/**
 * ET06 結果頁（AC 7 / AC 11）。
 *
 * ## 正確答案**強制顯示**
 *
 * `spec_us6` FR-09 明訂「MUST NOT 提供教師關閉正確答案顯示之選項」——這頁沒有任何
 * 條件式隱藏，看到的就是全部。成績單的用途是讓學員知道自己錯在哪。
 *
 * ## 結果來自提交時的回應（router state）
 *
 * 提交的回應已經帶了完整明細，再打一次 API 只是多一次往返。直接以網址進入（重新整理、
 * 貼連結）時沒有 state——那屬「歷次作答回看」的範圍（#280），此處明確提示而不是留白。
 */
export function EtQuizResultPage() {
  const navigate = useNavigate()
  const result = (useLocation().state ?? null) as AttemptResult | null

  if (result === null) {
    return (
      <Stack spacing={2}>
        <Alert severity="info">
          此頁顯示剛提交的成績。若要回看先前的作答紀錄，請自測驗引導頁進入「歷次作答紀錄」。
        </Alert>
        <Box>
          <Button variant="outlined" onClick={() => navigate("/et/my-courses")}>
            回到我的課程
          </Button>
        </Box>
      </Stack>
    )
  }

  const canRetry = !result.is_pass && result.remaining_attempts > 0
  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
        <Typography variant="h6">測驗完成</Typography>
        <Typography variant="h3" color={result.is_pass ? "success.main" : "error.main"} sx={{ my: 1 }}>
          {result.score} / 100 分
        </Typography>
        <Chip
          color={result.is_pass ? "success" : "error"}
          label={result.is_pass ? `合格（及格分數 ${result.pass_score}）` : `不合格（及格分數 ${result.pass_score}）`}
        />
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          第 {result.attempt_no} 次作答
          {/* 逾時自動提交仍照常計分——狀態如實標示，不假裝是正常提交 */}
          {result.status === "TIMEOUT" && "（作答時間到，已自動提交）"} ｜ 剩餘可作答{" "}
          {result.remaining_attempts} 次
        </Typography>

        {/* ET-MSG-ET06-004 */}
        {canRetry && (
          <Alert severity="warning" sx={{ mt: 2, textAlign: "left" }}>
            未達及格分數，您仍有重考機會
          </Alert>
        )}

        <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
          {canRetry && (
            <Button
              variant="contained"
              startIcon={<ReplayIcon />}
              onClick={() => navigate(`/et/quizzes/${result.quiz_id}`)}
            >
              重新作答
            </Button>
          )}
          <Button variant="outlined" onClick={() => navigate("/et/my-courses")}>
            回到我的課程
          </Button>
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          答題明細
        </Typography>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>題號</TableCell>
                <TableCell>題型</TableCell>
                <TableCell>你的答案</TableCell>
                <TableCell>正確答案</TableCell>
                <TableCell>結果</TableCell>
                <TableCell align="right">得分</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {result.questions.map((question, i) => {
                const outcome = OUTCOME_LABEL[question.outcome]
                return (
                  <TableRow key={question.question_id}>
                    <TableCell>Q{i + 1}</TableCell>
                    <TableCell>{question.question_type === "MULTIPLE" ? "多選" : "單選"}</TableCell>
                    <TableCell>{optionText(question.options, (o) => o.selected)}</TableCell>
                    {/* AC 11：強制顯示，無教師可關閉之選項 */}
                    <TableCell>{optionText(question.options, (o) => o.is_correct)}</TableCell>
                    <TableCell>
                      <Chip size="small" color={outcome.color} label={outcome.text} />
                    </TableCell>
                    <TableCell align="right">
                      {question.score} / {question.points}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  )
}
