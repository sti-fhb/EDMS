import PlayArrowIcon from "@mui/icons-material/PlayArrow"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import FormControlLabel from "@mui/material/FormControlLabel"
import FormGroup from "@mui/material/FormGroup"
import Grid from "@mui/material/Grid"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Radio from "@mui/material/Radio"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { AttemptHistory } from "./AttemptHistory"
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
 * ET07 測驗資訊與作答入口（AC 1 / AC 2）。
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
  /*
    ⚠️ 預覽與學員共用上半部（名稱、說明、三格考試規則），**下半部完全分流**。

    共用的是「這份測驗的規則長怎樣」——那是教師在 ET05 設定的東西，他本來就該看得到。
    分流的是作答相關的一切：剩餘次數、作答注意事項、`can_start` 的兩句訊息、歷次作答，
    對一個不會作答的人全都不成立（他的「剩餘次數」是個從未用過的滿值）。
  */
  const tileSize = data.is_preview ? { xs: 4, md: 4 } : { xs: 6, md: 3 }
  return (
    <Stack spacing={3}>
      <Typography variant="h6">{data.quiz_name}</Typography>
      {data.description && <Typography variant="body2">{data.description}</Typography>}

      <Grid container spacing={2}>
        <Grid size={tileSize}>
          <InfoTile value={String(data.question_count)} label="題數" />
        </Grid>
        <Grid size={tileSize}>
          {/* `null` = 不限時。**不可顯示「0 分」**——那會讓學員以為一進去就結束 */}
          <InfoTile
            value={data.time_limit_min === null ? "不限時" : String(data.time_limit_min)}
            unit={data.time_limit_min === null ? undefined : "分"}
            label="作答時間"
          />
        </Grid>
        <Grid size={tileSize}>
          <InfoTile value={String(data.pass_score)} unit="分" label="及格分數" />
        </Grid>
        {!data.is_preview && (
          <Grid size={tileSize}>
            <InfoTile value={String(data.remaining_attempts)} unit="次" label="剩餘可作答" />
          </Grid>
        )}
      </Grid>

      {data.is_preview && <QuizPreviewQuestions quizId={quizId} />}

      {!data.is_preview && (
        <>
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
          {/*
            這條與其他四條分開、加粗：其他四條講的是「別這樣做，否則不方便」，這條講的是
            「這樣做會直接失去這次作答」。混在同一串等寬文字裡會被當成一般叮嚀讀過去。
          */}
          <ListItem sx={{ display: "list-item", py: 0 }} disablePadding>
            <ListItemText
              primary="作答期間切換到其他視窗或分頁，將立即自動提交本次作答"
              slotProps={{ primary: { variant: "body2", fontWeight: "bold" } }}
            />
          </ListItem>
        </List>
      </Alert>

      {/*
        **inline 而非 Snackbar**——這是頁面的持續狀態，不是一次性事件。

        ⚠️ `can_start === false` 有兩種成因，訊息不可混為一句：課程關閉時叫學員「聯繫教師
        重置」是叫他去做一件沒有用的事（重置的是重考次數，不會讓關閉的課程重新開放）。
      */}
      {!data.can_start &&
        (data.course_closed ? (
          /* ET-MSG-ET07-005（#280 裁示 Q3 = B：不輪詢，於此與成績頁事後告知）*/
          <Alert severity="warning">此課程已關閉，無法再開新作答</Alert>
        ) : (
          /* ET-MSG-ET07-001 */
          <Alert severity="info">重考次數已用完，請聯繫教師重置</Alert>
        ))}

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
      </Stack>

      {/*
        歷次清單取代 #279 的「查看上次作答明細」單點入口（#280 裁示 Q2 = B）。那顆按鈕
        本來就是 `ET-6b` 未交付前的過渡——學員想回看的往往是第 1 次，只給最近一次等於
        把最有價值的那筆藏起來。**不受 `can_start` 影響**：次數用完的學員最需要複習。
      */}
      <AttemptHistory quizId={quizId} />
        </>
      )}
    </Stack>
  )
}

/**
 * 預覽模式的唯讀題目（#486，2026-10-01 裁示）。
 *
 * ## 為何是唯讀而不是讓教師實際作答
 *
 * 實際作答會在 `ET_QUIZ_ATTEMPT` 留下教師的列。系統原本允許**擁有者**這樣做（並以
 * 「不掛 `ET_ENROLLMENT` 故不進 US9 統計」為由），但 #481 把預覽擴大到非擁有者之後，
 * 那個論證要重新成立一次，而裁示選擇了更小的面：預覽只看，不寫。
 *
 * ## ⚠️ 這裡看得到的不是學員會看到的順序
 *
 * 學員每次作答都依該次 attempt 的快照洗牌（題目與選項皆然）。預覽回答得出「題目寫了
 * 什麼」，回答不出「他會以什麼順序看到」——與預覽看不出依序解鎖是同一類的固有限制，
 * 故一併寫在提示裡。
 */
function QuizPreviewQuestions({ quizId }: { quizId: number }) {
  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etQuiz.preview(quizId),
    queryFn: () => attemptApi.preview(quizId),
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 2 }}>
        <CircularProgress size={20} />
      </Stack>
    )
  }
  if (error) {
    return <Alert severity="error">{toApiError(error).errorMessage}</Alert>
  }

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        <strong>預覽模式</strong>
        <Typography variant="body2">
          以下為學員會看到的題目內容，<strong>本頁不會記錄作答</strong>。實際作答時題目與選項順序會隨機排列，
          且不顯示正確答案——正確答案請於課程編輯的測驗設定中確認。
        </Typography>
      </Alert>

      {data.questions.length === 0 ? (
        /* 0 題的測驗在學員端不當閘門（#361），但教師多半是忘了出題——明說比留白有用 */
        <Alert severity="warning">此測驗尚未新增任何題目，學員目前看不到任何內容。</Alert>
      ) : (
        data.questions.map((q, index) => (
          <Paper key={q.question_id} variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="subtitle2">第 {index + 1} 題</Typography>
              <Chip
                size="small"
                color={q.question_type === "MULTIPLE" ? "info" : "default"}
                label={q.question_type === "MULTIPLE" ? "多選題" : "單選題"}
              />
              <Typography variant="caption" color="text.secondary">
                {q.points} 分
              </Typography>
            </Stack>
            <Typography variant="body2" sx={{ mb: 1 }}>
              {q.stem}
            </Typography>
            <FormGroup>
              {q.options.map((o) => (
                <FormControlLabel
                  key={o.option_id}
                  // `disabled` 而非自行畫一顆灰圈：原生的停用態同時擋掉鍵盤與讀屏的
                  // 互動，自繪的只是看起來不能點。
                  control={
                    q.question_type === "MULTIPLE" ? <Checkbox disabled checked={false} /> : <Radio disabled checked={false} />
                  }
                  label={<Typography variant="body2">{o.text}</Typography>}
                />
              ))}
            </FormGroup>
          </Paper>
        ))
      )}
    </Stack>
  )
}
