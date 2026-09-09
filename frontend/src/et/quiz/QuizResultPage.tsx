import ChevronRightIcon from "@mui/icons-material/ChevronRight"
import ReplayIcon from "@mui/icons-material/Replay"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"

import { AnswerReviewDialog } from "./AnswerReviewDialog"
import type { QuestionResult, ResultNavState } from "./attemptSchemas"
import { attemptApi } from "./attemptService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { toApiError } from "../../services/http"

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
 * ET06 結果頁（AC 7 / AC 11）——剛提交的成績單，也是「查看上次作答明細」的複習頁。
 *
 * ## 兩種進入方式
 *
 * | 來源 | 資料 |
 * |---|---|
 * | 剛提交（`navigate` 帶 state）| 直接用提交的回應 |
 * | 引導頁的「查看上次作答明細」／重新整理／貼連結 | `GET /attempts/{id}/result` |
 *
 * 有 state 時不重抓——那份回應就是同一份成績（分數於提交當下凍結，後端也是讀存下來的
 * 值而非重算）。
 *
 * ## 正確答案**強制顯示**
 *
 * `spec_us6` FR-09 明訂「MUST NOT 提供教師關閉正確答案顯示之選項」。表格只給摘要，
 * 完整題幹與逐選項對錯在[檢討視窗](./AnswerReviewDialog.tsx)——表格不顯示題目，未點開
 * 之前不必看到。
 */
export function EtQuizResultPage() {
  const navigate = useNavigate()
  const { attemptId: attemptIdParam } = useParams<{ attemptId: string }>()
  const attemptId = Number(attemptIdParam)
  const routerState = (useLocation().state ?? null) as ResultNavState | null
  // state 一律優先於網址，所以**必須**確認它講的是同一次作答。不比對的話「網址是 A、
  // 畫面渲染 B 的成績」會是一個完全無警訊的 bug——分數、題目、答案全部照常渲染。
  const fromSubmit = routerState?.attempt_id === attemptId ? routerState : null
  const [reviewIndex, setReviewIndex] = useState<number | null>(null)
  const needsFetch = fromSubmit === null && Number.isFinite(attemptId) && attemptId > 0

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etQuiz.result(attemptId),
    queryFn: () => attemptApi.result(attemptId),
    enabled: needsFetch,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const result = fromSubmit ?? data ?? null

  // `enabled: false` 時 `isPending` 恆為 true，故轉圈的條件必須連 `needsFetch` 一起判——
  // 否則網址代碼無效會停在一個永遠不會結束的轉圈上
  if (needsFetch && isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (result === null) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">{error ? toApiError(error).errorMessage : "查無此作答紀錄"}</Alert>
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
      {/*
        為什麼考卷會突然被交出去，必須說清楚——不說的話學員只會看到一個他沒按過提交的
        成績頁，而那看起來像系統壞掉。
      */}
      {fromSubmit?.left_window === true && (
        <Alert severity="warning">因離開作答視窗，本次作答已自動提交。</Alert>
      )}

      <Paper variant="outlined" sx={{ p: 3, textAlign: "center" }}>
        <Typography variant="h6">測驗完成</Typography>
        <Typography variant="h3" color={result.is_pass ? "success.main" : "error.main"} sx={{ my: 1 }}>
          {result.score} / {result.points_total} 分
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
          {/*
            **只留這一顆**。重考的入口只有一個：學習頁的測驗面板——從這裡直接開新的
            attempt 會少掉作答注意事項，而且誤觸就吃掉一次次數。學習頁會依 `LAST_ITEM_ID`
            自動落回該測驗項目，所以回去就看得到「開始作答」；要去別的課程，那頁的返回
            路徑本來就通到我的課程，不必在這裡再開一條。
          */}
          <Button
            variant="contained"
            startIcon={canRetry ? <ReplayIcon /> : undefined}
            onClick={() => navigate(`/et/courses/${result.course_id}/learn`)}
          >
            {canRetry ? "回課程重新作答" : "返回課程"}
          </Button>
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>
          答題明細
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          點任一列檢視該題的完整題目與選項。
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
                <TableCell sx={{ width: 40 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {result.questions.map((question, i) => {
                const outcome = OUTCOME_LABEL[question.outcome]
                return (
                  <TableRow key={question.question_id} hover sx={{ cursor: "pointer" }} onClick={() => setReviewIndex(i)}>
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
                    <TableCell>
                      {/*
                        整列可點是給滑鼠的；`<tr>` 本身不可聚焦，鍵盤使用者需要一個真的
                        按鈕才進得去這個視窗。點它時不再冒泡觸發整列那一次。
                      */}
                      <IconButton
                        size="small"
                        aria-label={`檢視第 ${i + 1} 題`}
                        onClick={(e) => {
                          e.stopPropagation()
                          setReviewIndex(i)
                        }}
                      >
                        <ChevronRightIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <AnswerReviewDialog
        question={reviewIndex === null ? null : (result.questions[reviewIndex] ?? null)}
        index={reviewIndex ?? 0}
        onClose={() => setReviewIndex(null)}
      />
    </Stack>
  )
}
