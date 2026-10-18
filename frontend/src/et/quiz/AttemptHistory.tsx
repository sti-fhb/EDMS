import ChevronRightIcon from "@mui/icons-material/ChevronRight"
import HistoryIcon from "@mui/icons-material/History"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { usePinQuizInUrl } from "./usePinQuizInUrl"

import { resetLabel, withRoundDividers, type RoundBoundary } from "./attemptRounds"
import { attemptApi } from "./attemptService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"

/**
 * 歷次作答紀錄（#280 AC 1 / AC 2）。
 *
 * ## 沒有「本次」標示
 *
 * wireframe 把當次 attempt 以底色標出，那是因為它原本畫在**成績頁**。#280 裁示 Q2 = B
 * 把清單移到測驗面板後，畫面上並沒有「正在看的那一次」——標示無所指，故不做。
 *
 * ## 為何整份清單、而不是只給「上一次」
 *
 * #279 只交付了「查看上次作答明細」的單點入口，那是 `ET-6b` 未交付前的過渡。學員想回看
 * 的往往正是**第 1 次**（看看自己進步了多少、或第一次錯在哪），只給最近一次等於把最有
 * 價值的那筆藏起來。故依 `ATTEMPT_NO` **遞增**排列，與 wireframe 一致。
 *
 * ## 課程關閉／被移除後仍可看
 *
 * 後端的授權只看 `USER_ID`、不問課程資格（`spec_us6` 場景 25 / 28）。故本元件**不接受**
 * 任何「是否可見」的旗標——可見與否不是它該判斷的事，拿得到資料就顯示。
 *
 * 零筆時整塊不顯示：一張空表格會讓學員以為系統把他的紀錄弄丟了。
 *
 * ## 依輪次分段（#709）
 *
 * 教師要求重測或重置重考次數後，新一輪的第一筆之前插一列分隔（日期＋原因）；最近一次
 * **要求重測**之前的作答標「前一輪」並轉灰（不計入成績），逐題明細**仍可點開**——舊輪是
 * 學員的歷史，不是作廢。重置重考次數不影響成績，故只有分隔列、不轉灰。
 */
export function AttemptHistory({ quizId, resets = [] }: { quizId: number; resets?: readonly RoundBoundary[] }) {
  const navigate = useNavigate()
  const pinQuizInUrl = usePinQuizInUrl(quizId)
  /** 先釘住學習頁網址再進結果頁（#549）——結果頁的「返回課程」會退回這一筆。 */
  const openResult = async (attemptId: number) => {
    await pinQuizInUrl()
    await navigate(`/et/attempts/${attemptId}/result`)
  }
  const { data } = useQuery({
    queryKey: QUERY_KEYS.etQuiz.history(quizId),
    queryFn: () => attemptApi.history(quizId),
    enabled: Number.isFinite(quizId) && quizId > 0,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  // 載入中與零筆都不佔版面——這是輔助資訊，不該讓主要動作（開始作答）往下推
  if (!data || data.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <HistoryIcon fontSize="small" color="action" />
        <Typography variant="subtitle1">歷次作答紀錄</Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        每次作答皆獨立記錄；結業成績以最高分為準。點任一列可回看該次的逐題明細。
      </Typography>
      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>次別</TableCell>
              <TableCell>作答時間</TableCell>
              <TableCell align="right">分數</TableCell>
              <TableCell>是否及格</TableCell>
              <TableCell sx={{ width: 40 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {withRoundDividers(data, resets).map((row) =>
              row.type === "divider" ? (
                <RoundDividerRow key={`reset-${row.reset.after_attempt_no}-${row.reset.executed_at}`} reset={row.reset} />
              ) : (
              <TableRow
                key={row.attempt.attempt_id}
                hover
                sx={{ cursor: "pointer", ...(row.previous && { "& td": { color: "text.disabled" } }) }}
                onClick={() => void openResult(row.attempt.attempt_id)}
              >
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <strong>第 {row.attempt.attempt_no} 次</strong>
                    {/* 逾時自動提交如實標示，不假裝是正常提交 */}
                    {row.attempt.status === "TIMEOUT" && <Chip size="small" variant="outlined" label="逾時" />}
                    {row.previous && <Chip size="small" variant="outlined" label="前一輪" />}
                  </Stack>
                </TableCell>
                <TableCell>{formatDateTime(row.attempt.submitted_at)}</TableCell>
                <TableCell align="right">
                  {row.attempt.score} / {row.attempt.points_total}
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    // 前一輪的及格／未及格不再代表現況——去色，避免綠色「及格」誤導
                    color={row.previous ? "default" : row.attempt.is_pass ? "success" : "error"}
                    label={row.attempt.is_pass ? "及格" : "未及格"}
                  />
                </TableCell>
                <TableCell>
                  {/* 整列可點是給滑鼠的；`<tr>` 不可聚焦，鍵盤使用者需要一顆真的按鈕 */}
                  <IconButton
                    size="small"
                    aria-label={`回看第 ${row.attempt.attempt_no} 次作答明細`}
                    onClick={(e) => {
                      e.stopPropagation()
                      void openResult(row.attempt.attempt_id)
                    }}
                  >
                    <ChevronRightIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
              ),
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  )
}

/** 輪次分隔列（#709）——與 ET02 作答明細同一套文字。 */
export function RoundDividerRow({ reset, colSpan = 5 }: { reset: RoundBoundary; colSpan?: number }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} sx={{ bgcolor: "action.hover", py: 0.5 }}>
        <Typography variant="caption" color="text.secondary">
          {formatDateTime(reset.executed_at)} · {resetLabel(reset.kind)}
        </Typography>
      </TableCell>
    </TableRow>
  )
}
