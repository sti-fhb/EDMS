import CheckCircleIcon from "@mui/icons-material/CheckCircle"
import CancelIcon from "@mui/icons-material/Cancel"
import RemoveCircleIcon from "@mui/icons-material/RemoveCircle"
import Box from "@mui/material/Box"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import LinearProgress from "@mui/material/LinearProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { studentsApi } from "./studentsService"
import type { OptionResult, QuestionResult } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"

/**
 * 三態的顏色與 icon——沿用 ET-6b `AnswerReviewDialog` 的語彙。
 *
 * `titleAccess` 讓 icon 進入無障礙樹：MUI 的 `SvgIcon` 預設帶 `aria-hidden="true"`，
 * 只給 `aria-label` 會被它蓋掉（#283 踩過，且 `getByLabelText` 抓不到那個假綠）。
 */
const OUTCOME = {
  CORRECT: { color: "success.main", label: "答對", Icon: CheckCircleIcon },
  PARTIAL: { color: "warning.main", label: "部分對", Icon: RemoveCircleIcon },
  WRONG: { color: "error.main", label: "答錯", Icon: CancelIcon },
} as const

/** 選項的三種標示：選對＝綠、選錯＝紅、漏選的正確答案＝黃。 */
function optionColor(option: OptionResult): string | undefined {
  if (option.is_selected && option.is_correct) return "success.main"
  if (option.is_selected && !option.is_correct) return "error.main"
  if (!option.is_selected && option.is_correct) return "warning.main"
  return undefined
}

function QuestionRow({ question, index }: { question: QuestionResult; index: number }) {
  const outcome = OUTCOME[question.outcome]
  return (
    <Box sx={{ borderLeft: 3, borderColor: outcome.color, pl: 2, py: 1 }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <outcome.Icon fontSize="small" titleAccess={outcome.label} sx={{ color: outcome.color }} />
        <Typography variant="subtitle2">Q{index + 1}. {question.stem}</Typography>
        <Chip size="small" label={`${question.score} / ${question.points}`} />
      </Stack>
      <Stack spacing={0.5} sx={{ mt: 1 }}>
        {question.options.map((option) => (
          <Typography key={option.option_id} variant="body2" sx={{ color: optionColor(option) }}>
            {option.is_selected ? "☑" : "☐"} {option.option_text}
            {!option.is_selected && option.is_correct && "（正確答案，未選）"}
          </Typography>
        ))}
      </Stack>
    </Box>
  )
}

/**
 * 教師端檢視某次 attempt 的逐題明細（`FR-ET-US9-05`）。
 *
 * ⚠️ 走的是**教師端端點** `/et/attempts/{id}/detail`（以課程擁有權授權），不是學員端的
 * `/result`（以 `USER_ID` 比對）。兩者刻意分開——放寬學員端那支會讓任何學員拿
 * `attempt_id` 就能看別人的考卷。
 *
 * 逐題內容依**該次 attempt 的快照**渲染，與學員端同一份資料：教師與學員對著同一次作答
 * 必須看到相同的對錯與得分。
 */
export function TeacherAttemptDialog({ attemptId, onClose }: { attemptId: number | null; onClose: () => void }) {
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEYS.etStudents.attemptDetail(attemptId ?? 0),
    queryFn: () => studentsApi.attemptDetail(attemptId as number),
    enabled: attemptId !== null,
  })

  return (
    <Dialog open={attemptId !== null} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>
        {data ? (
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <span>
              {data.user_name ?? "—"} — {data.quiz_name}（第 {data.attempt_no} 次）
            </span>
            <Chip
              size="small"
              color={data.is_pass ? "success" : "default"}
              label={`${data.score} / ${data.points_total} ${data.is_pass ? "及格" : "未及格"}`}
            />
          </Stack>
        ) : (
          "作答明細"
        )}
      </DialogTitle>
      <DialogContent dividers>
        {isPending && attemptId !== null && <LinearProgress />}
        {isError && <Typography color="error">作答明細載入失敗</Typography>}
        {data && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              {(["CORRECT", "PARTIAL", "WRONG"] as const).map((key) => {
                const item = OUTCOME[key]
                return (
                  <Stack key={key} direction="row" spacing={0.5} alignItems="center">
                    <item.Icon fontSize="small" titleAccess={item.label} sx={{ color: item.color }} />
                    <Typography variant="caption">{item.label}</Typography>
                  </Stack>
                )
              })}
            </Stack>
            {data.questions.map((question, index) => (
              <QuestionRow key={question.question_id} question={question} index={index} />
            ))}
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  )
}
