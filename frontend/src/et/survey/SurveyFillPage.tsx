import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import LockIcon from "@mui/icons-material/Lock"
import SendIcon from "@mui/icons-material/Send"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import FormControl from "@mui/material/FormControl"
import FormControlLabel from "@mui/material/FormControlLabel"
import FormHelperText from "@mui/material/FormHelperText"
import FormLabel from "@mui/material/FormLabel"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Radio from "@mui/material/Radio"
import RadioGroup from "@mui/material/RadioGroup"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useNavigate, useParams } from "react-router-dom"

import {
  ANSWER_TEXT_MAX_LEN,
  draftFromAnswers,
  isReadOnly,
  toAnswerPayload,
  unansweredSingleIds,
} from "./surveyFillSchemas"
import type { AnswerDraft, SurveyForm, SurveyQuestionRow } from "./surveyFillSchemas"
import { surveyFillApi } from "./surveyFillService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"

/**
 * ET05 課後問卷填寫頁（US13 / #284）。
 *
 * 填寫、唯讀回看、課程已關閉三態共用同一個版面，由後端的 `state` 分支——三者要顯示的
 * **題目是同一份**，差別只在能不能改與有沒有送出鈕。
 *
 * ## 單選必答、問答選填
 *
 * FR-ET-US13-03（2026-08-28 裁示）：問答題留空**不阻擋送出**。理由是「問卷是回饋工具
 * 而非考試，強制作答只會換來『.』『無意見』之類的內容，反而讓教師誤判回收品質」。
 *
 * ⚠️ issue body 驗收條件 3 寫「全部題目作答後方可送出」，那是加入問答題之前的敘述。
 *
 * ## 送出鈕不 disable，而是擋下並提示
 *
 * wireframe 與 issue 都寫「未全答時送出鈕禁用」，但 `disabled` 的按鈕點下去毫無反應，
 * 學員不會知道是哪一題沒填——問卷有十幾題時他得自己一題一題找。故一律可點，由
 * `handleSubmit` 判定後以頂部 Alert + 逐題紅框標出未答題（ET-MSG-ET05-101），與
 * `ChapterNav` 對鎖定項目的處理同一個立場（#255：阻擋**並提示**）。
 */
export function EtSurveyFillPage() {
  const { courseId: courseIdParam } = useParams<{ courseId: string }>()
  const courseId = Number(courseIdParam)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message, confirm } = useNotification()

  const [draft, setDraft] = useState<AnswerDraft>({})
  const [showErrors, setShowErrors] = useState(false)

  // 路由參數非數字（網址被手改）時 query 的 `enabled` 為 false，`isPending` 會恆為
  // true——使用者只會看到一個永遠轉不完的圈。提前給明確訊息。
  const courseIdValid = Number.isFinite(courseId) && courseId > 0

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etSurvey.form(courseId),
    queryFn: () => surveyFillApi.form(courseId),
    enabled: courseIdValid,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const backToCourse = useCallback(() => navigate(`/et/courses/${courseId}/learn`), [courseId, navigate])

  const submitting = useMutation({
    /**
     * `ET_SURVEY_013`（已填寫過）在此**轉為成功**，不走 `onError`。
     *
     * 開兩個分頁各按一次送出時，第二次的 409 是**正確結果**——他的問卷確實已經送出。
     *
     * ⚠️ 這段判斷必須在 `mutationFn` 內，不能放在 `onError`：`mutateAsync()` 無論
     * `onError` 有沒有處理都會 reject，而送出是由 `confirm({ onOk })` 觸發的——
     * `onOk` 一 reject，`NotificationContext` 就只解除 loading、**刻意保留對話框**
     * （那是給真正失敗的情境用的）。結果會是「綠色成功提示」與「確認對話框」同時
     * 留在畫面上、也不導頁。
     */
    mutationFn: async () => {
      try {
        await surveyFillApi.submit(courseId, toAnswerPayload(data?.questions ?? [], draft))
      } catch (err) {
        if (toApiError(err).errorCode !== "ET_SURVEY_013") throw err
      }
    },
    onSuccess: () => {
      message.success("問卷已送出，感謝您的回饋")
      // 側欄入口要從「填寫課後問卷」變成「查看我的填答」——那份狀態在 `/learn` 的
      // 回應裡，不重抓的話學員回到課程頁會看到已經不成立的入口。
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.etLearn.structure(courseId) })
      // 表單本身也要失效：他從入口再點進來時該看到唯讀的自己填答，而非填寫態。
      void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.etSurvey.form(courseId) })
      backToCourse()
    },
    onError: (err) => message.error(toApiError(err).errorMessage),
  })

  // 已送出者的作答由伺服器狀態推導，**不複製進 state**——複製一份只會多一個要同步的
  // 來源，而 query 重抓時那份會過期。填寫中的 `draft` 才是本地狀態。
  const readOnly = data !== undefined && isReadOnly(data.state)
  const effectiveDraft = useMemo(
    () => (data?.state === "SUBMITTED" ? draftFromAnswers(data.my_answers) : draft),
    [data, draft],
  )
  const unanswered = useMemo(
    () => new Set(unansweredSingleIds(data?.questions ?? [], effectiveDraft)),
    [data, effectiveDraft],
  )

  const handleSubmit = useCallback(() => {
    if (data === undefined) return
    if (unanswered.size > 0) {
      setShowErrors(true)
      return
    }
    confirm({
      title: "送出問卷",
      content: "送出後即不可修改，確定送出嗎？",
      okText: "送出",
      onOk: () => submitting.mutateAsync().then(() => undefined),
    })
  }, [confirm, data, submitting, unanswered])

  if (!courseIdValid) {
    return (
      <PageFrame onBack={() => navigate("/et/my-courses")}>
        <Alert severity="error">課程代碼無效</Alert>
      </PageFrame>
    )
  }
  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (error) {
    return (
      <PageFrame onBack={backToCourse}>
        <Alert severity="error">{toApiError(error).errorMessage}</Alert>
      </PageFrame>
    )
  }

  return (
    <PageFrame onBack={backToCourse} title={data.survey_name}>
      <Paper variant="outlined" sx={{ maxWidth: 760, mx: "auto", p: { xs: 2, sm: 4 } }}>
        <StateBanner data={data} />

        {/* 未答提示（ET-MSG-ET05-101）。inline 而非 Snackbar——與欄位並存才看得出是哪一次送出。 */}
        {showErrors && unanswered.size > 0 && (
          <Alert severity="error" sx={{ mb: 3 }}>
            尚有題目未作答，請完成後再送出
          </Alert>
        )}

        <Stack spacing={3} divider={<Divider flexItem />}>
          {data.questions.map((question, index) => (
            <QuestionField
              key={question.sq_id}
              question={question}
              index={index}
              value={effectiveDraft[question.sq_id]}
              readOnly={readOnly}
              error={showErrors && unanswered.has(question.sq_id)}
              onChange={(next) => {
                setDraft((prev) => ({ ...prev, [question.sq_id]: next }))
                // 一改就把提示收掉：使用者正在修正，繼續紅著只是噪音。整體的未答判定
                // 仍在送出時重跑，不會因此放行。
                setShowErrors(false)
              }}
            />
          ))}
        </Stack>

        <Divider sx={{ my: 3 }} />
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
          <Button variant="outlined" size="small" startIcon={<ArrowBackIcon />} onClick={backToCourse}>
            返回課程
          </Button>
          {!readOnly && (
            <Button
              variant="contained"
              startIcon={<SendIcon />}
              onClick={handleSubmit}
              disabled={submitting.isPending}
            >
              送出問卷
            </Button>
          )}
        </Stack>
      </Paper>
    </PageFrame>
  )
}

/** 三態各自的頂部說明。 */
function StateBanner({ data }: { data: SurveyForm }) {
  if (data.state === "COURSE_CLOSED") {
    return (
      <Alert severity="warning" icon={<LockIcon />} sx={{ mb: 3 }}>
        課程已關閉，無法填寫問卷
      </Alert>
    )
  }
  if (data.state === "SUBMITTED") {
    return (
      <Alert severity="info" sx={{ mb: 3 }}>
        您已於 {formatDateTime(data.submitted_at)} 送出，內容不可修改。
      </Alert>
    )
  }
  if (data.state === "HIDDEN") {
    // 完課回退（教師新增章節）後仍可取到表單。已填者是 `SUBMITTED`，走到這裡的是
    // 「還沒填完課就退回去了」——說明為什麼送不出，而不是給一個點了會失敗的鈕。
    return (
      <Alert severity="info" sx={{ mb: 3 }}>
        課程尚未完成，完課後即可填寫本問卷。
      </Alert>
    )
  }
  return (
    <Alert severity="info" sx={{ mb: 3 }}>
      本問卷為<strong>具名</strong>填答；一人一次，送出後不可修改。填寫問卷不是完課條件、不計入學習進度。
    </Alert>
  )
}

interface QuestionFieldProps {
  question: SurveyQuestionRow
  index: number
  value: { so_id?: number; answer_text?: string } | undefined
  readOnly: boolean
  error: boolean
  onChange: (next: { so_id?: number; answer_text?: string }) => void
}

function QuestionField({ question, index, value, readOnly, error, onChange }: QuestionFieldProps) {
  const isSingle = question.question_type === "SINGLE"
  const text = value?.answer_text ?? ""

  return (
    <FormControl error={error} fullWidth>
      {/* 必填星號只給單選題——問答題標星號會讓學員以為非填不可（FR-03 明訂選填）。 */}
      <FormLabel required={isSingle} sx={{ fontWeight: 600, color: "text.primary" }}>
        {index + 1}. {question.stem}
      </FormLabel>
      {isSingle ? (
        <RadioGroup
          value={value?.so_id ?? ""}
          onChange={(event) => onChange({ so_id: Number(event.target.value) })}
          sx={{ mt: 1 }}
        >
          {question.options.map((option) => (
            <FormControlLabel
              key={option.so_id}
              value={option.so_id}
              control={<Radio size="small" />}
              label={option.option_text}
              disabled={readOnly}
            />
          ))}
        </RadioGroup>
      ) : (
        <TextField
          multiline
          minRows={2}
          fullWidth
          size="small"
          sx={{ mt: 1 }}
          value={text}
          onChange={(event) => onChange({ answer_text: event.target.value })}
          disabled={readOnly}
          placeholder={readOnly ? "（未填）" : "選填"}
          helperText={readOnly ? undefined : `${text.length} / ${ANSWER_TEXT_MAX_LEN}`}
          slotProps={{ htmlInput: { maxLength: ANSWER_TEXT_MAX_LEN, "aria-label": question.stem } }}
        />
      )}
      {error && <FormHelperText>尚未作答</FormHelperText>}
    </FormControl>
  )
}

function PageFrame({
  onBack,
  title,
  children,
}: {
  onBack: () => void
  title?: string
  children: ReactNode
}) {
  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        {/* 目的地寫進 label：底部另有一顆「返回課程」按鈕，同名會讓螢幕閱讀器與
            測試都分不出兩者。比照 `LearnPage` 的 `返回我的課程`。 */}
        <IconButton size="small" aria-label="返回章節學習" onClick={onBack}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5">{title ?? "課後問卷"}</Typography>
      </Stack>
      {children}
    </Box>
  )
}
