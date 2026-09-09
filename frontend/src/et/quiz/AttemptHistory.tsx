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

import { attemptApi } from "./attemptService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { toApiError } from "../../services/http"

/** `2026-05-22 14:05`——秒對回看沒有意義，只會讓欄位變寬。 */
function formatSubmittedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

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
 */
export function AttemptHistory({ quizId }: { quizId: number }) {
  const navigate = useNavigate()
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
            {data.map((attempt) => (
              <TableRow
                key={attempt.attempt_id}
                hover
                sx={{ cursor: "pointer" }}
                onClick={() => navigate(`/et/attempts/${attempt.attempt_id}/result`)}
              >
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <strong>第 {attempt.attempt_no} 次</strong>
                    {/* 逾時自動提交如實標示，不假裝是正常提交 */}
                    {attempt.status === "TIMEOUT" && <Chip size="small" variant="outlined" label="逾時" />}
                  </Stack>
                </TableCell>
                <TableCell>{formatSubmittedAt(attempt.submitted_at)}</TableCell>
                <TableCell align="right">{attempt.score}</TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    color={attempt.is_pass ? "success" : "error"}
                    label={attempt.is_pass ? "及格" : "未及格"}
                  />
                </TableCell>
                <TableCell>
                  {/* 整列可點是給滑鼠的；`<tr>` 不可聚焦，鍵盤使用者需要一顆真的按鈕 */}
                  <IconButton
                    size="small"
                    aria-label={`回看第 ${attempt.attempt_no} 次作答明細`}
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/et/attempts/${attempt.attempt_id}/result`)
                    }}
                  >
                    <ChevronRightIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  )
}
