import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"
import FormControlLabel from "@mui/material/FormControlLabel"
import Grid from "@mui/material/Grid"
import Paper from "@mui/material/Paper"
import Radio from "@mui/material/Radio"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { useBlocker, useLocation, useNavigate, useParams } from "react-router-dom"

import { carryFirstEntry } from "../../hooks/useGoBack"

import type { AttemptState, QuestionForAnswering, ResultNavState } from "./attemptSchemas"
import { attemptApi } from "./attemptService"
import { CountdownTimer } from "./CountdownTimer"
import { QuestionNav } from "./QuestionNav"
import { useAutoSubmitOnLeave } from "./useAutoSubmitOnLeave"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/**
 * ET07 答題頁（AC 4 / AC 5 / AC 6）。
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
/**
 * 倒數剩下多少毫秒內，點選選項就立即暫存（#608）。與倒數轉為警示色的門檻同為 60 秒。
 *
 * ⚠️ 不能完全消除「最後一刻的作答被拒」：後端以 `int()` 捨去剩餘秒數，最後不到 1 秒內的
 * 點選仍會被判逾時。要消除須改後端計時或給寬限——屬規格層級決定，未在此處理。
 */
const FINAL_SAVE_WINDOW_MS = 60_000

/** 是否已進入「點選即存」的最後一分鐘；不限時（`null`）恆為 false。只在事件處理中呼叫。 */
function isInFinalSaveWindow(deadlineMs: number | null): boolean {
  return deadlineMs !== null && deadlineMs - Date.now() <= FINAL_SAVE_WINDOW_MS
}

export function EtQuizAnswerPage() {
  const { attemptId: attemptIdParam } = useParams<{ attemptId: string }>()
  const attemptId = Number(attemptIdParam)
  const navigate = useNavigate()
  /**
   * 進結果頁一律 `replace`（#549）：作答頁不留在歷程裡，結果頁的上一頁就是學習頁。
   *
   * 🔴 本頁若是工作階段第一筆（直接貼網址 / 書籤），replace 會換掉 `"default"` key，結果頁的
   * 返回便以為有上一頁而離站——state 經 `carryFirstEntry` 帶上「第一筆」標記（code review /
   * security review）。
   */
  const location = useLocation()
  const toResult = (state?: ResultNavState) =>
    navigate(`/et/attempts/${attemptId}/result`, { replace: true, state: carryFirstEntry(location, state) })
  const { message } = useNotification()
  const attemptIdValid = Number.isFinite(attemptId) && attemptId > 0

  const [currentId, setCurrentId] = useState<number | null>(null)
  /** 本地作答（尚未送出暫存的也在內）；key 為 `question_id`。 */
  const [answers, setAnswers] = useState<Record<number, number[]>>({})
  /** 已送出暫存的題目——避免切題時重送沒有變動的答案。 */
  const savedRef = useRef<Record<number, string>>({})
  /**
   * 每題最後一個暫存請求；同一題的暫存一律接在它後面送出（#608）。
   *
   * 最後一分鐘點選即存會對同一題連發。並行送出的話落地順序不保證：伺服器可能留下較舊的
   * 選擇，而較新那筆的回應較晚回來、`savedRef` 記成較新的值——提交時判定「已存」而不補送，
   * 學員以畫面上沒有的答案計分，且無任何訊號。
   */
  const saveChainRef = useRef<Record<number, Promise<void>>>({})
  const submittingRef = useRef(false)

  const { data, isPending, isFetchedAfterMount, error, refetch } = useQuery({
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
    // 🔴 **每次進入本頁都向伺服器重抓**（#608），且重抓完成前不渲染作答（見下方
    // `isFetchedAfterMount`）。本地作答是在 `queryFn` 裡灌入的，而 `staleTime` 是無限大：
    // 不這樣做的話，離開後 5 分鐘內再次進入作答頁會直接吐出第一次載入時的舊快取、`queryFn`
    // 不執行，本地作答與 `savedRef` 都是空的——畫面顯示舊答案，切題時再把看過沒動的題目
    // 暫存成空白，覆蓋伺服器上已存的作答。
    // ⛔ 不要改用 `gcTime: 0`：快取是卸載後**下一輪**才回收，立刻回到本頁仍會吃到舊快取。
    refetchOnMount: "always",
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  /** 把一筆暫存接在該題前一筆之後送出（前一筆失敗也照送）；成功才記入 `savedRef`。 */
  const saveInOrder = useCallback(
    (questionId: number, selected: number[]): Promise<void> => {
      const previous = saveChainRef.current[questionId] ?? Promise.resolve()
      const next = previous
        .catch(() => undefined)
        .then(async () => {
          await attemptApi.saveAnswer(attemptId, questionId, selected)
          savedRef.current[questionId] = JSON.stringify(selected)
        })
      saveChainRef.current[questionId] = next
      return next
    },
    [attemptId],
  )

  /**
   * 送出單題暫存。
   *
   * @param required 失敗時是否往外拋。
   *   - `false`（切換題目）：靜默——切題不該因為暫存失敗而卡住，提交前還會再送一次。
   *   - `true`（**提交前**）：必須拋。學員在最後一題作答後直接按提交時，這是那一題唯一
   *     的落地機會；靜默吞掉會讓它從閱卷中消失，而學員看到的是「已提交並完成閱卷」。
   */
  const flushAnswer = useCallback(
    async (questionId: number | null, { required = false }: { required?: boolean } = {}) => {
      if (questionId === null) return
      // 先等該題排隊中的暫存落地，`savedRef` 才是伺服器上的實際值
      await (saveChainRef.current[questionId] ?? Promise.resolve()).catch(() => undefined)
      const selected = answers[questionId] ?? []
      if (savedRef.current[questionId] === JSON.stringify(selected)) return
      try {
        await saveInOrder(questionId, selected)
      } catch (err) {
        if (required) throw err
      }
    },
    [answers, saveInOrder],
  )

  /** 本次提交是不是「離開作答視窗」觸發的——結果頁要據此說明為什麼考卷被交出去。 */
  const leftWindowRef = useRef(false)
  /** 本次提交是站內離開（經確認）觸發的——交完放行原本的導覽，不進結果頁（#640）。 */
  const leavingViaNavRef = useRef(false)

  const submit = useMutation({
    mutationFn: async () => {
      // ⚠️ 先把**所有**尚未暫存成功的題目送出去，不只當前題（#608）——
      // 最後一題作答後直接提交會漏掉那一題；切題時暫存失敗（靜默）的題目也只剩這次機會。
      // `required` 讓失敗會中止提交並顯示錯誤，而不是送出一份缺題的考卷。
      const pending = Object.keys(answers)
        .map(Number)
        .sort((a, b) => (a === currentId ? -1 : b === currentId ? 1 : 0))
      try {
        for (const questionId of pending) await flushAnswer(questionId, { required: true })
      } catch (err) {
        // 🔴 時間已到（`ET_ATTEMPT_005`）**照樣交卷**（#608）：後端剩餘秒數無條件捨去、前端倒數
        // 進位，倒數歸零時後端必已逾時、暫存一定被拒；中止的話倒數只自動觸發一次、手動按提交
        // 又走同一條暫存——學員永遠交不了卷。`submit` 本身不受時限限制（spec_us6），以已存的
        // 作答閱卷；被拒的那一筆就是最後一刻的變動，由下方「最後一分鐘點選即存」盡量提早落地。
        if (toApiError(err).errorCode !== "ET_ATTEMPT_005") throw err
      }
      return attemptApi.submit(attemptId)
    },
    onSuccess: (result) => {
      if (leavingViaNavRef.current) {
        // 目的地由確認視窗的 `blocker.proceed()` 前往，這裡不導向結果頁
        message.success("已提交本次作答")
        return
      }
      const left = leftWindowRef.current
      message.success(left ? "已離開作答視窗，本次作答已自動提交" : "已提交並完成閱卷")
      const state: ResultNavState = left ? { ...result, left_window: true } : result
      // `replace`（#549）：作答完不該能用上一頁回到作答中；結果頁的上一頁是學習頁
      void toResult(state)
    },
    onError: (err) => {
      submittingRef.current = false
      leftWindowRef.current = false
      leavingViaNavRef.current = false
      message.error(toApiError(err).errorMessage)
    },
  })

  const doSubmit = useCallback(() => {
    if (submittingRef.current) return
    submittingRef.current = true
    submit.mutate()
  }, [submit])

  const submitOnLeave = useCallback(() => {
    if (submittingRef.current) return
    // 在 `doSubmit` **之前**設旗標：`onSuccess` 讀的是它，晚設會讓自動提交看起來像手動提交
    leftWindowRef.current = true
    doSubmit()
  }, [doSubmit])

  // 作答中離開視窗 → 自動交卷。`enabled` 讓已提交的 attempt 與載入中都不掛監聽——
  // 否則「已提交後用上一頁回來」再切個分頁就會打一次注定 409 的提交。
  useAutoSubmitOnLeave({ enabled: data?.status === "IN_PROGRESS", onLeave: submitOnLeave })

  /**
   * 作答中由**站內**離開（左側選單、瀏覽器上一頁、頁內連結）→ 確認後交卷再放行（#640）。
   *
   * 切換視窗攔不住、只能直接交；站內導覽攔得住，故先確認——誤點側欄的代價是一次作答次數。
   * 這推翻了 #280 裁示 Q1 = B（不實作防誤離確認）在**站內導覽**的部分：該裁示的前提是
   * 「離開一定交卷」，而站內導覽在 #640 之前根本不交卷（才有續作）；關閉分頁仍直接交、
   * 不確認，那部分的裁示照舊。
   *
   * ⚠️ **交卷成功才放行**：交卷失敗時學員要留在作答頁、看得到錯誤、可重試或改按「繼續作答」。
   * 先放行的話他已經離開——錯誤訊息落在別頁、作答停在作答中，他不知道自己沒交成。
   * （不是為了「請求被丟掉」：站內導覽不重新載入頁面、卸載也不取消已送出的請求。）
   * 交卷中（含自己按提交後 `replace` 進結果頁）不攔——`submittingRef` 已為 true。
   */
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      data?.status === "IN_PROGRESS" && !submittingRef.current && currentLocation.pathname !== nextLocation.pathname,
  )
  /** 確認「提交並離開」：交卷成功才放行原本的導覽；失敗時 `onError` 已提示，留在本頁。 */
  const submitAndLeave = async () => {
    if (submittingRef.current) return
    submittingRef.current = true
    leavingViaNavRef.current = true
    try {
      await submit.mutateAsync()
    } catch {
      return
    }
    blocker.proceed?.()
  }

  if (!attemptIdValid) return <Alert severity="error">作答代碼無效</Alert>
  // 快取裡的舊資料不可拿來作答（#608）：本次進入後的重抓回來、本地作答灌入之前一律等待
  if (isPending || (!isFetchedAfterMount && !error)) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (error) {
    // 每次進入都重抓（見上方 `refetchOnMount`），重抓失敗就沒有快取可退——給一顆重新載入，
    // 學員在作答時限內不必整頁重新整理（重新整理在本系統等於重新登入）
    return (
      <Alert
        severity="error"
        action={
          <Button size="small" onClick={() => void refetch()}>
            重新載入
          </Button>
        }
      >
        {toApiError(error).errorMessage}
      </Alert>
    )
  }
  if (data.status !== "IN_PROGRESS") {
    // 已提交後用上一頁回到本頁——不要讓學員對著一份已經交出去的考卷繼續作答，
    // 那會一路寫到按提交才收到 409。導向這次的成績，那才是他回來想找的東西。
    return (
      <Alert
        severity="info"
        action={
          <Button size="small" onClick={() => void toResult()}>
            查看成績
          </Button>
        }
      >
        本次作答已提交，無法再變更。
      </Alert>
    )
  }

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
    // `question.selected_options` 已是「本地優先、否則伺服器值」（見上方 `questions`）
    const currentSelection = question.selected_options
    const next =
      question.question_type === "SINGLE"
        ? [optionId]
        : currentSelection.includes(optionId)
          ? currentSelection.filter((id) => id !== optionId)
          : [...currentSelection, optionId]
    setAnswers((prev) => ({ ...prev, [question.question_id]: next }))
    // 最後一分鐘點選即存（#608）：平時切題 / 提交才送（多選題勾四個不必四個請求），但倒數
    // 將盡時「提交前的暫存」會撞上逾時被拒——點選當下就送，歸零前的作答才來得及落地。
    // 失敗不擋操作：提交時會再補送一次。
    if (isInFinalSaveWindow(data.deadlineMs)) {
      void saveInOrder(question.question_id, next).catch(() => undefined)
    }
  }

  return (
    <Box>
      {/*
        站內離開的確認（#640）。**本頁自己渲染、不用全域 `confirm`**：確認視窗開著時若觸發
        自動交卷（切視窗 / 倒數歸零），交完會 `replace` 進結果頁、本頁卸載——全域對話框不隨
        本頁卸載，會留在結果頁上，按「提交並離開」對已交的考卷再送一次（409）。本頁的對話框
        隨本頁一起消失。條件渲染而非 `open={false}` 常駐（見 MUI Dialog 的 aria-hidden 坑）。
      */}
      {blocker.state === "blocked" && (
        <Dialog open onClose={() => !submit.isPending && blocker.reset?.()}>
          <DialogTitle>離開作答</DialogTitle>
          <DialogContent>
            <DialogContentText>離開將立即提交本次作答，確定離開？</DialogContentText>
          </DialogContent>
          <DialogActions>
            <Button disabled={submit.isPending} onClick={() => blocker.reset?.()}>
              繼續作答
            </Button>
            <Button variant="contained" disabled={submit.isPending} onClick={() => void submitAndLeave()}>
              提交並離開
            </Button>
          </DialogActions>
        </Dialog>
      )}
      {/*
        常駐而非一次性 Snackbar：這是整段作答期間都成立的規則，而 Snackbar 幾秒後就消失，
        學員在第 8 分鐘切走分頁時早就看不到它了。
      */}
      <Alert severity="warning" sx={{ mb: 2 }}>
        <strong>請勿切換視窗或分頁</strong>——離開本畫面將立即自動提交本次作答。
      </Alert>

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
