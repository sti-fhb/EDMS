import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import EditOutlinedIcon from "@mui/icons-material/EditOutlined"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import InputAdornment from "@mui/material/InputAdornment"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { QuestionEditor } from "./QuestionEditor"
import {
  EMPTY_QUESTION,
  POINTS_TOTAL_TARGET,
  QUESTION_TYPE_LABEL,
  QUIZ_DESCRIPTION_MAX_LEN,
  QUIZ_NAME_MAX_LEN,
} from "./itemSchemas"
import type { QuestionDraft, QuestionFormValues, QuestionRow, QuestionType, QuizDetail } from "./itemSchemas"

interface QuizDialogProps {
  open: boolean
  loading: boolean
  readOnly: boolean
  quiz: QuizDetail | null
  error: string | null
  onClose: () => void
  onSaveSettings: (values: {
    quiz_name: string
    description: string | null
    pass_score: number
    time_limit_min: number | null
    max_retry: number
  }) => void
  onSaveQuestion: (questionId: number | null, values: QuestionFormValues) => void
  onDeleteQuestion: (question: QuestionRow) => void
}

/**
 * 測驗編輯視窗（ET02）——設定與題庫分頁。
 *
 * ## 配分總和只顯示、不阻擋
 *
 * 教師是逐題新增的，第 1 題存檔時總和必然不是 100。此處常駐顯示「90 / 100」並在
 * 未達標時以警示色提醒，但**不擋儲存**——阻擋發布是 #204 的事（FR-ET-US3-11）。
 *
 * ## 題目順序不提供教師調整入口
 *
 * spec：題目順序由系統內建洗牌，教師不設定。故題庫頁沒有拖拉手把——
 * 後端雖有 `SORT_ORDER` 與重排端點（供日後需要時使用），UI 刻意不暴露。
 */
export function QuizDialog({
  open,
  loading,
  readOnly,
  quiz,
  error,
  onClose,
  onSaveSettings,
  onSaveQuestion,
  onDeleteQuestion,
}: QuizDialogProps) {
  const [tab, setTab] = useState(0)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [passScore, setPassScore] = useState(80)
  const [timeLimit, setTimeLimit] = useState("")
  const [maxRetry, setMaxRetry] = useState(3)
  const [loadedId, setLoadedId] = useState<number | null>(null)
  /** 目前展開編輯的題目 id；`"new"` 表示新增中；`null` 表示沒有展開任何題目。 */
  const [editing, setEditing] = useState<number | "new" | null>(null)

  // render 期間衍生 state——載入新測驗時把表單重設為它的值（不放 useEffect）
  if (quiz && loadedId !== quiz.quiz_id) {
    setLoadedId(quiz.quiz_id)
    setName(quiz.quiz_name)
    setDescription(quiz.description ?? "")
    setPassScore(quiz.pass_score)
    setTimeLimit(quiz.time_limit_min === null ? "" : String(quiz.time_limit_min))
    setMaxRetry(quiz.max_retry)
    setEditing(null)
  }
  if (!open && loadedId !== null) setLoadedId(null)

  const handleSaveSettings = () => {
    onSaveSettings({
      quiz_name: name,
      description: description.trim() || null,
      pass_score: passScore,
      // 留空 = 不限時（後端之兩態語意：null 或 >= 1，0 不是有效值）
      time_limit_min: timeLimit.trim() === "" ? null : Number(timeLimit),
      max_retry: maxRetry,
    })
  }

  const handleSaveQuestion = (values: QuestionFormValues) => {
    onSaveQuestion(editing === "new" ? null : editing, values)
    setEditing(null)
  }

  const toDraft = (question: QuestionRow): QuestionDraft => ({
    question_type: question.question_type as QuestionType,
    stem: question.stem,
    points: question.points,
    options: question.options.map((o) => ({ option_text: o.option_text, is_correct: o.is_correct })),
  })

  const pointsTotal = quiz?.points_total ?? 0
  const pointsOk = pointsTotal === POINTS_TOTAL_TARGET

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{readOnly ? "檢視測驗" : "編輯測驗"}</DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Stack alignItems="center" sx={{ py: 6 }}>
            <CircularProgress />
          </Stack>
        ) : (
          <>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            <Tabs value={tab} onChange={(_, next) => setTab(next)} sx={{ mb: 2 }}>
              <Tab label="測驗設定" />
              <Tab label={`題庫管理（${quiz?.questions.length ?? 0}）`} />
            </Tabs>

            {tab === 0 && (
              <Stack spacing={2} sx={{ pt: 1 }}>
                <TextField
                  label="測驗名稱"
                  required
                  size="small"
                  fullWidth
                  value={name}
                  disabled={readOnly}
                  slotProps={{ htmlInput: { maxLength: QUIZ_NAME_MAX_LEN } }}
                  onChange={(e) => setName(e.target.value)}
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    label="及格分數"
                    required
                    size="small"
                    type="number"
                    value={passScore}
                    disabled={readOnly}
                    slotProps={{
                      htmlInput: { min: 0, max: 100 },
                      input: { endAdornment: <InputAdornment position="end">分</InputAdornment> },
                    }}
                    onChange={(e) => setPassScore(Number(e.target.value))}
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="作答時間限制"
                    size="small"
                    type="number"
                    value={timeLimit}
                    disabled={readOnly}
                    helperText="留空 = 不限時"
                    slotProps={{
                      htmlInput: { min: 1 },
                      input: { endAdornment: <InputAdornment position="end">分鐘</InputAdornment> },
                    }}
                    onChange={(e) => setTimeLimit(e.target.value)}
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="重考次數上限"
                    required
                    size="small"
                    type="number"
                    value={maxRetry}
                    disabled={readOnly}
                    helperText="0 = 不允許重考"
                    slotProps={{ htmlInput: { min: 0, max: 999 } }}
                    onChange={(e) => setMaxRetry(Number(e.target.value))}
                    sx={{ flex: 1 }}
                  />
                </Stack>
                <TextField
                  label="測驗說明（顯示於開始前）"
                  size="small"
                  fullWidth
                  multiline
                  minRows={3}
                  value={description}
                  disabled={readOnly}
                  helperText="純文字，不支援格式化"
                  slotProps={{ htmlInput: { maxLength: QUIZ_DESCRIPTION_MAX_LEN } }}
                  onChange={(e) => setDescription(e.target.value)}
                />
                <Alert severity="info" variant="outlined">
                  題目順序由系統內建洗牌——學員每次作答時自動隨機排序，無需教師設定。
                </Alert>
              </Stack>
            )}

            {tab === 1 && (
              <Stack spacing={1.5} sx={{ pt: 1 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Chip
                    size="small"
                    color={pointsOk ? "success" : "warning"}
                    variant={pointsOk ? "filled" : "outlined"}
                    label={`配分總和 ${pointsTotal} / ${POINTS_TOTAL_TARGET}`}
                  />
                  {!readOnly && (
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<AddIcon />}
                      disabled={editing !== null}
                      onClick={() => setEditing("new")}
                    >
                      新增題目
                    </Button>
                  )}
                </Stack>
                {!pointsOk && (
                  <Typography variant="caption" color="text.secondary">
                    配分總和須等於 {POINTS_TOTAL_TARGET} 才能發布課程；此處不阻擋儲存。
                  </Typography>
                )}

                {quiz?.questions.length === 0 && editing !== "new" && (
                  <Typography variant="body2" color="text.disabled" sx={{ py: 3, textAlign: "center" }}>
                    尚無題目——點「新增題目」開始建立題庫
                  </Typography>
                )}

                {quiz?.questions.map((question, index) =>
                  editing === question.question_id ? (
                    <QuestionEditor
                      key={question.question_id}
                      initial={toDraft(question)}
                      onSave={handleSaveQuestion}
                      onCancel={() => setEditing(null)}
                    />
                  ) : (
                    <Paper key={question.question_id} variant="outlined" sx={{ p: 1.5 }}>
                      <Stack direction="row" alignItems="flex-start" spacing={1}>
                        <Typography variant="body2" fontWeight={700} sx={{ minWidth: 28, pt: 0.5 }}>
                          Q{index + 1}
                        </Typography>
                        <Chip
                          size="small"
                          variant="outlined"
                          label={QUESTION_TYPE_LABEL[question.question_type as QuestionType] ?? question.question_type}
                        />
                        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                          <Typography variant="body2">{question.stem}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            {question.options.length} 個選項 ｜ 正確{" "}
                            {question.options.filter((o) => o.is_correct).length} 個
                          </Typography>
                        </Box>
                        <Chip size="small" label={`${question.points} 分`} />
                        {!readOnly && (
                          <>
                            <IconButton
                              size="small"
                              aria-label={`編輯第 ${index + 1} 題`}
                              disabled={editing !== null}
                              onClick={() => setEditing(question.question_id)}
                            >
                              <EditOutlinedIcon fontSize="small" />
                            </IconButton>
                            <IconButton
                              size="small"
                              color="error"
                              aria-label={`刪除第 ${index + 1} 題`}
                              onClick={() => onDeleteQuestion(question)}
                            >
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          </>
                        )}
                      </Stack>
                    </Paper>
                  ),
                )}

                {editing === "new" && (
                  <QuestionEditor
                    initial={EMPTY_QUESTION}
                    onSave={handleSaveQuestion}
                    onCancel={() => setEditing(null)}
                  />
                )}
              </Stack>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{readOnly ? "關閉" : "關閉"}</Button>
        {!readOnly && tab === 0 && (
          <Button variant="contained" disabled={loading} onClick={handleSaveSettings}>
            儲存設定
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
