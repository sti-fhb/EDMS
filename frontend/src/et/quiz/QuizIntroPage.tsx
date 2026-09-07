import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import PlayArrowIcon from "@mui/icons-material/PlayArrow"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Grid from "@mui/material/Grid"
import IconButton from "@mui/material/IconButton"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate, useParams } from "react-router-dom"

import { attemptApi } from "./attemptService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/** 引導頁的四格資訊卡（wireframe `et-quiz-intro` 的 `row g-3`）。 */
function InfoTile({ value, unit, label }: { value: string; unit?: string; label: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, textAlign: "center" }}>
      <Typography variant="h5" component="div">
        {value}
        {unit && (
          <Typography variant="body2" component="span" sx={{ ml: 0.5 }}>
            {unit}
          </Typography>
        )}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Paper>
  )
}

/**
 * ET06 測驗引導頁（AC 1 / AC 2）。
 *
 * 「開始作答」實際呼叫的是「開始或繼續」——後端在有未完成 attempt 時回既有那一筆
 *（SA 裁示 Q1 = A）。前端只依 `in_progress_attempt_id` 換按鈕文案，**不自行判斷**該建新
 * 的還是續作：那個判定在後端，兩邊各判一次遲早會分岔。
 */
export function EtQuizIntroPage() {
  const { quizId: quizIdParam } = useParams<{ quizId: string }>()
  const quizId = Number(quizIdParam)
  const navigate = useNavigate()
  const { message } = useNotification()
  const quizIdValid = Number.isFinite(quizId) && quizId > 0

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etQuiz.intro(quizId),
    queryFn: () => attemptApi.intro(quizId),
    enabled: quizIdValid,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const start = useMutation({
    mutationFn: () => attemptApi.start(quizId),
    onSuccess: (attempt) => navigate(`/et/attempts/${attempt.attempt_id}`),
    onError: (err) => message.error(toApiError(err).errorMessage),
  })

  if (!quizIdValid) {
    return <Alert severity="error">測驗代碼無效</Alert>
  }
  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (error) {
    return <Alert severity="error">{toApiError(error).errorMessage}</Alert>
  }

  const resuming = data.in_progress_attempt_id !== null
  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <IconButton size="small" aria-label="返回課程" onClick={() => navigate(-1)}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5">{data.quiz_name}</Typography>
      </Stack>

      <Paper variant="outlined" sx={{ p: 3 }}>
        <Stack spacing={3}>
          {data.description && <Typography variant="body2">{data.description}</Typography>}

          <Grid container spacing={2}>
            <Grid size={{ xs: 6, md: 3 }}>
              <InfoTile value={String(data.question_count)} label="題數" />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              {/* `null` = 不限時。**不可顯示「0 分」**——那會讓學員以為一進去就結束 */}
              <InfoTile
                value={data.time_limit_min === null ? "不限時" : String(data.time_limit_min)}
                unit={data.time_limit_min === null ? undefined : "分"}
                label="作答時間"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <InfoTile value={String(data.pass_score)} unit="分" label="及格分數" />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <InfoTile value={String(data.remaining_attempts)} unit="次" label="剩餘可作答" />
            </Grid>
          </Grid>

          {data.best_score !== null && (
            <Alert severity={data.is_passed ? "success" : "info"}>
              {/* 兩個都顯示——結業成績取最高分，只給最近一次會讓重考後考差的學員以為自己退步了 */}
              最近一次成績 <strong>{data.last_score}</strong> 分；最高分{" "}
              <strong>{data.best_score}</strong> 分（結業成績以最高分為準）
              {data.is_passed && " — 已及格"}
            </Alert>
          )}

          <Alert severity="warning">
            <strong>作答注意事項</strong>
            <List dense disablePadding sx={{ listStyleType: "disc", pl: 3 }}>
              {[
                "點擊「開始作答」後立即計時，中途離開或關閉視窗仍持續扣時間",
                "作答時請勿重新整理或返回上一頁，避免遺失作答狀態",
                "未達及格分數時，可依剩餘次數重新作答；以最高分為結業成績",
                "提交後立即顯示成績與每題對錯明細",
              ].map((text) => (
                <ListItem key={text} sx={{ display: "list-item", py: 0 }} disablePadding>
                  <ListItemText primary={text} slotProps={{ primary: { variant: "body2" } }} />
                </ListItem>
              ))}
            </List>
          </Alert>

          {/* ET-MSG-ET06-001；**inline 而非 Snackbar**——這是頁面的持續狀態，不是一次性事件 */}
          {!data.can_start && <Alert severity="info">重考次數已用完，請聯繫教師重置</Alert>}

          <Stack direction="row" spacing={2} justifyContent="center">
            <Button variant="outlined" onClick={() => navigate(-1)}>
              取消
            </Button>
            <Button
              variant="contained"
              size="large"
              startIcon={<PlayArrowIcon />}
              disabled={!data.can_start || start.isPending}
              onClick={() => start.mutate()}
            >
              {resuming ? "繼續作答" : "開始作答"}
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  )
}
