import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import FormControlLabel from "@mui/material/FormControlLabel"
import Grid from "@mui/material/Grid"
import Paper from "@mui/material/Paper"
import Radio from "@mui/material/Radio"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import type { AttemptState, QuestionForAnswering } from "./attemptSchemas"
import { attemptApi } from "./attemptService"
import { CountdownTimer } from "./CountdownTimer"
import { QuestionNav } from "./QuestionNav"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/**
 * ET06 答題頁（AC 4 / AC 5 / AC 6）。
 *
 * ## 作答狀態是本地的，暫存是背景的
 *
 * 學員每點一下選項就送一次請求會讓多選題變得很慢（勾四個 = 四個請求），故本地先更新、
 * **切換題目與提交前**才送出暫存。這也是 wireframe 寫的「切換題目時系統自動暫存」。
 *
 * ⚠️ **提交前一定要先把當前題的暫存送出去**——否則學員在最後一題作答後直接按提交，
 * 那一題永遠不會被存進去，而他明明看到自己選了。這是最容易漏的一步，因為手動測試時
 * 幾乎都會先切過題目。
 *
 * ## 倒數只是顯示
 *
 * 逾時的真正判定在後端（提交當下比對 `STARTED_AT + 時限`）。倒數歸零時前端自動提交，
 * 但即使那個計時器被停掉、分頁被凍結，學員也拿不到額外時間。
 */
export function EtQuizAnswerPage() {
  const { attemptId: attemptIdParam } = useParams<{ attemptId: string }>()
  const attemptId = Number(attemptIdParam)
  const navigate = useNavigate()
  const { message } = useNotification()
  const attemptIdValid = Number.isFinite(attemptId) && attemptId > 0

  const [currentId, setCurrentId] = useState<number | null>(null)
  /** 本地作答（尚未送出暫存的也在內）；key 為 `question_id`。 */
  const [answers, setAnswers] = useState<Record<number, number[]>>({})
  /** 已送出暫存的題目——避免切題時重送沒有變動的答案。 */
  const savedRef = useRef<Record<number, string>>({})
  const submittingRef = useRef(false)

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etQuiz.attempt(attemptId),
    queryFn: async () => {
      const state = await attemptApi.state(attemptId)
      // 伺服器狀態灌進本地一次；之後以本地為準（避免每次重取覆蓋掉未暫存的作答）
      setAnswers((prev) =>
        Object.keys(prev).length > 0 ? prev : Object.fromEntries(state.questions.map((q) => [q.question_id, q.selected_options])),
      )
      setCurrentId((prev) => prev ?? state.questions[0]?.question_id ?? null)
      for (const q of state.questions) savedRef.current[q.question_id] = JSON.stringify(q.selected_options)
      // **在收到回應的當下**錨定截止時點——晚一點錨（例如在元件 render 時）等於白送
      // 學員那段時間，而後端算的是自 `STARTED_AT` 起的絕對時限。
      return { ...state, deadlineMs: state.remaining_sec === null ? null : Date.now() + state.remaining_sec * 1000 }
    },
    enabled: attemptIdValid,
    // 作答中不要背景重抓——重抓會把伺服器上「尚未暫存」的舊答案蓋回畫面
    refetchOnWindowFocus: false,
    staleTime: Number.POSITIVE_INFINITY,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const flushAnswer = useCallback(
    async (questionId: number | null) => {
      if (questionId === null) return
      const selected = answers[questionId] ?? []
      if (savedRef.current[questionId] === JSON.stringify(selected)) return
      try {
        await attemptApi.saveAnswer(attemptId, questionId, selected)
        savedRef.current[questionId] = JSON.stringify(selected)
      } catch {
        // 靜默：切題不該因為暫存失敗而卡住；提交前會再送一次
      }
    },
    [answers, attemptId],
  )

  const submit = useMutation({
    mutationFn: async () => {
      // ⚠️ 先把當前題送出去——否則最後一題作答後直接提交會漏掉那一題
      await flushAnswer(currentId)
      return attemptApi.submit(attemptId)
    },
    onSuccess: (result) => {
      message.success("已提交並完成閱卷")
      navigate(`/et/attempts/${attemptId}/result`, { state: result })
    },
    onError: (err) => {
      submittingRef.current = false
      message.error(toApiError(err).errorMessage)
    },
  })

  const doSubmit = useCallback(() => {
    if (submittingRef.current) return
    submittingRef.current = true
    submit.mutate()
  }, [submit])

  if (!attemptIdValid) return <Alert severity="error">作答代碼無效</Alert>
  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (error) return <Alert severity="error">{toApiError(error).errorMessage}</Alert>

  const questions: QuestionForAnswering[] = data.questions.map((q) => ({
    ...q,
    selected_options: answers[q.question_id] ?? q.selected_options,
  }))
  const current = questions.find((q) => q.question_id === currentId) ?? questions[0] ?? null
  const index = current ? questions.findIndex((q) => q.question_id === current.question_id) : -1

  const goTo = (questionId: number) => {
    void flushAnswer(currentId)
    setCurrentId(questionId)
  }

  const toggle = (question: QuestionForAnswering, optionId: number) => {
    setAnswers((prev) => {
      const currentSelection = prev[question.question_id] ?? question.selected_options
      if (question.question_type === "SINGLE") return { ...prev, [question.question_id]: [optionId] }
      const next = currentSelection.includes(optionId)
        ? currentSelection.filter((id) => id !== optionId)
        : [...currentSelection, optionId]
      return { ...prev, [question.question_id]: next }
    })
  }

  return (
    <Box>
      {data.resumed && (
        <Alert severity="info" sx={{ mb: 2 }}>
          已回到您未完成的作答（第 {data.attempt_no} 次）。剩餘時間自開始作答時起算。
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2}>
          <Stack direction="row" spacing={2} alignItems="baseline">
            <Typography variant="subtitle1">
              題號進度{" "}
              <Typography component="span" variant="h6" color="primary">
                {index + 1} / {questions.length}
              </Typography>
            </Typography>
            <Typography variant="caption" color="text.secondary">
              及格分數：{data.pass_score} 分
            </Typography>
          </Stack>
          <CountdownTimer remainingSec={data.remaining_sec} deadlineMs={data.deadlineMs} onExpire={doSubmit} />
          <Button
            variant="contained"
            startIcon={<CheckCircleOutlineIcon />}
            disabled={submit.isPending}
            onClick={doSubmit}
          >
            提交
          </Button>
        </Stack>
      </Paper>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 3 }}>
          <QuestionNav questions={questions} currentQuestionId={current?.question_id ?? null} onSelect={goTo} />
        </Grid>
        <Grid size={{ xs: 12, md: 9 }}>
          {current === null ? (
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Alert severity="warning">此測驗沒有題目，請聯繫課程教師</Alert>
            </Paper>
          ) : (
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Stack spacing={2}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="subtitle2">
                    Q{index + 1} / {questions.length}
                  </Typography>
                  <Chip
                    size="small"
                    color={current.question_type === "MULTIPLE" ? "info" : "default"}
                    label={current.question_type === "MULTIPLE" ? "多選題" : "單選題"}
                  />
                  <Typography variant="caption" color="text.secondary">
                    配分：{current.points} 分
                  </Typography>
                </Stack>
                <Typography variant="body1">
                  <strong>{current.stem}</strong>
                </Typography>
                <Stack spacing={1}>
                  {current.options.map((option) => {
                    const checked = current.selected_options.includes(option.option_id)
                    return (
                      <Paper key={option.option_id} variant="outlined" sx={{ px: 1.5 }}>
                        <FormControlLabel
                          control={
                            current.question_type === "MULTIPLE" ? (
                              <Checkbox checked={checked} onChange={() => toggle(current, option.option_id)} />
                            ) : (
                              <Radio checked={checked} onChange={() => toggle(current, option.option_id)} />
                            )
                          }
                          label={option.text}
                          sx={{ width: "100%", py: 0.5 }}
                        />
                      </Paper>
                    )
                  })}
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Button
                    size="small"
                    disabled={index <= 0}
                    onClick={() => goTo(questions[index - 1].question_id)}
                  >
                    上一題
                  </Button>
                  <Button
                    size="small"
                    disabled={index >= questions.length - 1}
                    onClick={() => goTo(questions[index + 1].question_id)}
                  >
                    下一題
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          )}
        </Grid>
      </Grid>
    </Box>
  )
}

/** 供結果頁在直接以網址進入（無 router state）時回頭取用。 */
export type { AttemptState }
