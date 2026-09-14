import DownloadIcon from "@mui/icons-material/Download"
import Button from "@mui/material/Button"
import LinearProgress from "@mui/material/LinearProgress"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import ToggleButton from "@mui/material/ToggleButton"
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { BlockHeading } from "./BlockHeading"
import { studentsApi, studentsCsvPaths } from "./studentsService"
import { QUERY_KEYS } from "../../constants/queryKeys"

type View = "stats" | "details"

/**
 * ET03 區塊 3：問卷結果（`FR-ET-US9-07` / `-08`）。
 *
 * ## 課程無問卷時**整個區塊不渲染**
 *
 * `has_survey === false` 即回傳 `null`（AC 11 明訂隱藏）——不是顯示空狀態。顯示一塊
 * 「尚無問卷」會讓教師以為自己該去建一份，而問卷本來就是選配。
 *
 * ## 統計檢視的問答題只顯示已答人數
 *
 * 2026-08-28 裁示：長短不一的文字會把單選題的分布擠到看不見；問答題的價值在逐則閱讀，
 * 本就屬明細檢視。後端在統計區段根本不回文字，前端無從顯示。
 *
 * 🔴 **具名資料**——明細列出「誰說了什麼」，是本頁個資密度最高的一處。
 */
export function SurveyResultBlock({ courseId }: { courseId: number }) {
  const [view, setView] = useState<View>("stats")
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEYS.etStudents.surveyResult(courseId),
    queryFn: () => studentsApi.surveyResult(courseId),
  })

  if (isPending) return <LinearProgress />
  if (isError) return <Typography color="error">問卷結果載入失敗</Typography>
  // AC 11：課程無問卷時本區塊隱藏
  if (!data?.has_survey) return null

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        <BlockHeading
          index={3}
          title="問卷結果"
          note={`${data.survey_name ?? "課後問卷"} 填答結果，具名`}
        />
        <Stack direction="row" spacing={1} alignItems="center">
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_, next: View | null) => next && setView(next)}
          >
            <ToggleButton value="stats">統計</ToggleButton>
            <ToggleButton value="details">明細</ToggleButton>
          </ToggleButtonGroup>
          <Button
            size="small"
            startIcon={<DownloadIcon />}
            href={studentsCsvPaths.survey(courseId)}
            target="_blank"
            rel="noopener"
          >
            匯出 CSV
          </Button>
        </Stack>
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        已填 {data.filled_count} 人 ／ 未填 {data.not_filled_count} 人（母體為在籍學員）
      </Typography>

      {data.filled_count === 0 && (
        /* ET-MSG-ET03-006；題目仍列出，只是統計為 0 */
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          尚無學員填答問卷
        </Typography>
      )}

      {view === "stats" ? (
        <Stack spacing={3}>
          {data.questions.map((q) => (
            <Stack key={q.sq_id} spacing={1}>
              <Typography variant="subtitle2">{q.stem}</Typography>
              {q.options.length === 0 ? (
                /* 問答題：只有已答人數，文字在明細檢視（2026-08-28 裁示）*/
                <Typography variant="body2" color="text.secondary">
                  問答題 — 已答 {q.answered_count} 人（文字答案請切換至「明細」或匯出 CSV）
                </Typography>
              ) : (
                q.options.map((o) => {
                  const pct = q.answered_count > 0 ? Math.round((o.count / q.answered_count) * 100) : 0
                  return (
                    <Stack key={o.so_id} direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2" sx={{ minWidth: 120 }}>
                        {o.option_text}
                      </Typography>
                      <LinearProgress variant="determinate" value={pct} sx={{ flexGrow: 1, minWidth: 80 }} />
                      <Typography variant="caption" sx={{ minWidth: 80, textAlign: "right" }}>
                        {o.count} 人（{pct}%）
                      </Typography>
                    </Stack>
                  )
                })
              )}
            </Stack>
          ))}
        </Stack>
      ) : data.details.length === 0 ? (
        <Typography color="text.secondary" sx={{ py: 3, textAlign: "center" }}>
          尚無填答明細
        </Typography>
      ) : (
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>學員</TableCell>
                <TableCell>填答時間</TableCell>
                {data.questions.map((q) => (
                  <TableCell key={q.sq_id}>{q.stem}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {data.details.map((row) => {
                const byQuestion = new Map(row.answers.map((a) => [a.sq_id, a]))
                return (
                  <TableRow key={row.user_id} hover>
                    <TableCell>{row.user_name ?? "—"}</TableCell>
                    <TableCell>{new Date(row.submitted_at).toLocaleString("zh-TW")}</TableCell>
                    {data.questions.map((q) => {
                      const answer = byQuestion.get(q.sq_id)
                      return (
                        <TableCell key={q.sq_id}>
                          {/* 單選題顯示選項、問答題顯示文字；都沒有即未答該題 */}
                          {answer?.option_text ?? answer?.answer_text ?? "—"}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {data.questions.length === 0 && (
        <Typography color="text.secondary">此問卷尚無題目</Typography>
      )}
    </Paper>
  )
}
