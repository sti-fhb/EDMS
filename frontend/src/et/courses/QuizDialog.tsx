import AddIcon from "@mui/icons-material/Add"
import CloseIcon from "@mui/icons-material/Close"
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
  /** `dirty` 為 true 表示設定表單有未儲存的變更，由呼叫端決定是否先確認。 */
  onClose: (dirty: boolean) => void
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
 *
 * ## 底部按鈕只在「測驗設定」分頁出現
 *
 * 設定分頁：關閉 + 儲存（儲存＝存下設定並關閉）。
 * **題庫分頁沒有底部按鈕**——每一題自己就有「取消 / 儲存題目」，再放一組容易讓人
 * 以為那顆「儲存」會存題目（它只存設定），而「關閉」也不會檢核展開中的題目。
 * 關閉一律走標題列的 ✕，兩個分頁都在。
 *
 * 關閉前是否跳確認由 `isDirty` 決定——沒改過還問一次是干擾。**展開中的題目編輯器
 * 也算 dirty**：那裡面的內容同樣會因為關閉而消失。
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
  /** 送出前的驗證結果——逐欄標記，讓使用者知道要補哪一格而非「有東西不對」。 */
  const [nameError, setNameError] = useState<string | null>(null)

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

  /**
   * 是否有未儲存的變更。
   *
   * 已存檔的題目不算（各自即時儲存），但**展開中的題目編輯器算**——關閉視窗會讓
   * 那一題正在編輯的內容消失，使用者理應被提醒。
   */
  const isDirty =
    editing !== null ||
    (quiz !== null &&
    (name !== quiz.quiz_name ||
      description !== (quiz.description ?? "") ||
      passScore !== quiz.pass_score ||
      timeLimit !== (quiz.time_limit_min === null ? "" : String(quiz.time_limit_min)) ||
      maxRetry !== quiz.max_retry))

  const handleSaveSettings = () => {
    if (!name.trim()) {
      setNameError("請輸入測驗名稱")
      setTab(0) // 從題庫分頁按儲存時，把使用者帶回出問題的那一格
      return
    }
    setNameError(null)
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
    // 固定**整個對話框**的高度，而非只固定內容高度——底部按鈕只在設定分頁出現，
    // 光固定 DialogContent 仍會差一個 footer 的高度。內容超出時由 DialogContent 自行捲動。
    <Dialog
      open={open}
      onClose={() => onClose(isDirty)}
      maxWidth="md"
      fullWidth
      slotProps={{ paper: { sx: { height: "min(680px, 90vh)" } } }}
    >
      <DialogTitle sx={{ pr: 6 }}>
        {readOnly ? "檢視測驗" : "編輯測驗"}
        <IconButton
          // 名稱與底部的「關閉」刻意不同——設定分頁兩者並存，同名會讓輔助技術
          // 與測試都分不出是哪一顆
          aria-label="關閉視窗"
          onClick={() => onClose(isDirty)}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
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
                  error={Boolean(nameError)}
                  helperText={nameError}
                  slotProps={{ htmlInput: { maxLength: QUIZ_NAME_MAX_LEN } }}
                  onChange={(e) => {
                    setName(e.target.value)
                    // 邊打邊清掉錯誤——訊息留著不動會讓人以為改了還是不對
                    if (nameError) setNameError(null)
                  }}
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
                  slotProps={{ htmlInput: { maxLength: QUIZ_DESCRIPTION_MAX_LEN } }}
                  onChange={(e) => setDescription(e.target.value)}
                />
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
      {/* 只有設定分頁有底部按鈕——題庫分頁每題自帶「取消 / 儲存題目」，再放一組會混淆 */}
      {tab === 0 && (
        <DialogActions>
          <Button onClick={() => onClose(isDirty)}>關閉</Button>
          {!readOnly && (
            <Button variant="contained" disabled={loading} onClick={handleSaveSettings}>
              儲存
            </Button>
          )}
        </DialogActions>
      )}
    </Dialog>
  )
}
