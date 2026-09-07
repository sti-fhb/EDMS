import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import type { QuestionForAnswering, QuestionNavState } from "./attemptSchemas"
import { questionNavState } from "./attemptSchemas"

interface Props {
  questions: QuestionForAnswering[]
  currentQuestionId: number | null
  onSelect: (questionId: number) => void
}

/**
 * 左側題目導覽列（AC 5 / wireframe `quiz-nav-btn`）。
 *
 * 三態：已答（實心）/ 當前（外框強調）/ 未答（淡）。**全部可點**——跳題是這個元件存在
 * 的理由，未答的題目更是學員最需要跳過去的。
 *
 * 順序依 `questions` 陣列，而該陣列由後端依 attempt 的 `QUESTION_ORDER` 快照排好。
 * **前端不得自行排序**——同一次 attempt 內順序必須固定（AC 5），而快照就是那個固定。
 */
export function QuestionNav({ questions, currentQuestionId, onSelect }: Props) {
  const answered = questions.filter((q) => q.selected_options.length > 0).length
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        題目導覽
      </Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, mb: 2 }}>
        {questions.map((question, index) => {
          const state = questionNavState(question, currentQuestionId)
          return (
            <Button
              key={question.question_id}
              size="small"
              variant={_variant(state)}
              color={state === "answered" ? "success" : "primary"}
              onClick={() => onSelect(question.question_id)}
              aria-label={`第 ${index + 1} 題（${_label(state)}）`}
              sx={{ minWidth: 40, px: 0 }}
            >
              {index + 1}
            </Button>
          )
        })}
      </Box>
      <Stack spacing={0.5}>
        <Typography variant="caption" color="text.secondary">
          已答 {answered} / {questions.length}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          切換題目時系統自動暫存當前作答；可任意跳題。
        </Typography>
      </Stack>
    </Paper>
  )
}

function _variant(state: QuestionNavState) {
  if (state === "answered") return "contained" as const
  if (state === "current") return "outlined" as const
  return "text" as const
}

function _label(state: QuestionNavState) {
  if (state === "answered") return "已答"
  if (state === "current") return "當前題"
  return "未答"
}
