import HistoryIcon from "@mui/icons-material/History"
import PlayArrowIcon from "@mui/icons-material/PlayArrow"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Grid from "@mui/material/Grid"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { attemptApi } from "./attemptService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/** 四格資訊卡（wireframe `et-quiz-intro` 的 `row g-3`）。 */
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
 * ET06 測驗資訊與作答入口（AC 1 / AC 2）。
 *
 * ## 為何是面板而不是獨立頁
 *
 * 原本是 `/et/quizzes/:quizId` 一整頁，於是點側欄的測驗項目只會看到一顆「開始測驗」，
 * 按了才跳到真正的資訊頁——多一次跳轉、多一個畫面，而那個畫面的內容本來就該直接出現
 * 在點下去的地方。影片與文件項目都是就地渲染，測驗沒有理由是例外。
 *
 * 「開始作答」實際呼叫的是「開始或繼續」——後端在有未完成 attempt 時回既有那一筆
 *（SA 裁示 Q1 = A）。前端只依 `in_progress_attempt_id` 換按鈕文案，**不自行判斷**該建新
 * 的還是續作：那個判定在後端，兩邊各判一次遲早會分岔。
 */
export function QuizIntroPanel({ quizId }: { quizId: number }) {
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
    return <Alert severity="warning">此測驗內容不完整，請聯繫課程教師</Alert>
  }
  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 4 }}>
        <CircularProgress size={24} />
      </Stack>
    )
  }
  if (error) {
    return <Alert severity="error">{toApiError(error).errorMessage}</Alert>
  }

  const resuming = data.in_progress_attempt_id !== null
  return (
    <Stack spacing={3}>
      <Typography variant="h6">{data.quiz_name}</Typography>
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
          最近一次成績 <strong>{data.last_score}</strong> 分；最高分 <strong>{data.best_score}</strong> 分
          （結業成績以最高分為準）
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

      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
        <Button
          variant="contained"
          size="large"
          startIcon={<PlayArrowIcon />}
          disabled={!data.can_start || start.isPending}
          onClick={() => start.mutate()}
        >
          {resuming ? "繼續作答" : "開始作答"}
        </Button>
        {/*
          有作答紀錄就給複習入口，**不受 `can_start` 影響**：次數用完的學員正是最需要
          回頭看錯在哪的人，把複習跟著作答一起關掉等於懲罰他考不好。
        */}
        {data.last_attempt_id !== null && (
          <Button
            variant="outlined"
            size="large"
            startIcon={<HistoryIcon />}
            onClick={() => navigate(`/et/attempts/${data.last_attempt_id}/result`)}
          >
            查看上次作答明細
          </Button>
        )}
      </Stack>
    </Stack>
  )
}
