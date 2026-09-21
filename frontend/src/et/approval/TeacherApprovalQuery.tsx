import SearchIcon from "@mui/icons-material/Search"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import InputAdornment from "@mui/material/InputAdornment"
import MenuItem from "@mui/material/MenuItem"
import Pagination from "@mui/material/Pagination"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"
import { approvalsApi } from "./approvalsService"
import type { ApprovalQueryRow } from "./schemas"

/** 結果篩選的值域。`""` 代表不篩（wireframe 的「全部結果」）。 */
const RESULT_OPTIONS = [
  { value: "", label: "全部結果" },
  { value: "PASS", label: "僅通過" },
  { value: "FAIL", label: "僅不通過" },
] as const

/**
 * 教師 / 管理者視角——依學員姓名查核可紀錄（`FR-ET-US17-01`）。
 *
 * ## 🔴 範圍提示是 SA 裁示 C 的配套，不是可選的 UX 潤飾
 *
 * 裁示 C 讓教師看得到**全部課程的「通過且未撤銷」**，但「不通過」與「已撤銷」僅限
 * 自己 owner 的課程。後果是同一張表裡混了兩種範圍——教師看到某門課沒出現時，分不清
 * 是「還沒考」還是「考了沒過」。
 *
 * 少了那句提示，C 會比「只能查自己的課」更容易誤導：後者至少整份清單範圍一致。
 * 管理者不顯示（他沒有範圍限制）。
 *
 * ⚠️ 提示裡**必須包含「考核備註」**：SA 2026-09-21 追加裁示，他人課程的 `result_note`
 * 由後端遮蔽為 `null`（見 `query_service._enrich`）。若提示只提「不通過與已撤銷」，
 * 教師看到一列通過卻沒有備註時，會以為核可人沒寫，而不是被遮蔽了。
 *
 * ## 查詢前不顯示空狀態
 *
 * 「查無符合條件的核可紀錄」只在**查過之後**出現。一進畫面就顯示它，會讓教師以為
 * 系統已經查過而且真的沒有資料。
 */
export function TeacherApprovalQuery({ isAdmin }: { isAdmin: boolean }) {
  const [nameInput, setNameInput] = useState("")
  const [result, setResult] = useState("")
  const [page, setPage] = useState(1)
  /** 已送出的查詢條件。`null` = 尚未查詢過（與「查過但沒資料」是兩回事）。 */
  const [submitted, setSubmitted] = useState<{ user_name: string; result: string } | null>(null)
  /** 姓名欄位的本地驗證訊息。與下方查詢本身的 `queryError` 是兩回事，刻意分開命名。 */
  const [nameError, setNameError] = useState<string | null>(null)

  const params = submitted === null ? null : { ...submitted, page }
  const { data, isPending, isError, error: queryError } = usePagedQuery<ApprovalQueryRow>(
    QUERY_KEYS.etApprovals.search(params ?? {}),
    () =>
      approvalsApi.search({
        user_name: submitted!.user_name,
        result: (submitted!.result || undefined) as "PASS" | "FAIL" | undefined,
        page,
      }),
    { enabled: params !== null },
  )

  const submit = () => {
    // SA Q2 裁示 A：姓名必填。前端先擋是為了讓教師當場看到，後端仍會回 422。
    const keyword = nameInput.trim()
    if (keyword === "") {
      setNameError("請輸入學員姓名")
      return
    }
    setNameError(null)
    setPage(1)
    setSubmitted({ user_name: keyword, result })
  }

  const rows = data?.data ?? []
  const totalPages = data?.meta.total_pages ?? 0

  return (
    <Stack spacing={2}>
      {!isAdmin && (
        <Alert severity="info">
          已通過的紀錄涵蓋全部課程；<strong>不通過與已撤銷的紀錄、以及考核備註</strong>
          僅顯示您所開設的課程。
        </Alert>
      )}

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems="flex-start">
        <TextField
          label="學員姓名"
          size="small"
          sx={{ minWidth: 260 }}
          value={nameInput}
          error={nameError !== null}
          helperText={nameError ?? "可輸入部分姓名"}
          onChange={(e) => {
            setNameInput(e.target.value)
            setNameError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit()
          }}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />
        <TextField
          select
          label="核可結果"
          size="small"
          sx={{ minWidth: 150 }}
          value={result}
          onChange={(e) => setResult(e.target.value)}
        >
          {RESULT_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <Button variant="contained" size="medium" startIcon={<SearchIcon />} onClick={submit} sx={{ mt: 0.25 }}>
          查詢
        </Button>
      </Stack>

      {submitted === null ? (
        <Typography variant="body2" color="text.secondary">
          輸入學員姓名後按「查詢」。
        </Typography>
      ) : isPending ? (
        <Typography variant="body2" color="text.secondary">
          載入中…
        </Typography>
      ) : isError ? (
        // 🔴 **查詢失敗絕不可渲染成空狀態**。本頁的使用情境是「排班前確認某人受訓完整
        // 與否」，而「查無紀錄」會被讀成「這個人沒受過訓」——那是方向最危險的假陰性。
        //
        // 最容易撞到的是 429：查詢與核可寫入共用同一個 60/分 分桶（見 router docstring），
        // 教師翻幾頁又送幾次核可就會撞到。403 / 500 / 斷線在原本的寫法下也全長一樣。
        <Alert severity="error">{toApiError(queryError).errorMessage}</Alert>
      ) : rows.length === 0 ? (
        <Alert severity="info">查無符合條件的核可紀錄</Alert>
      ) : (
        <>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>學員</TableCell>
                  <TableCell>課程</TableCell>
                  <TableCell>核可結果</TableCell>
                  <TableCell>核可時間</TableCell>
                  <TableCell>核可人</TableCell>
                  <TableCell>狀態</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={`${row.course_id}:${row.user_id}`}
                    // 已撤銷整列淡化。⚠️ 用 opacity 而非 `color="text.secondary"`——
                    // 後者會把 Chip 的顏色也一起吃掉，通過 / 不通過就分不出來了。
                    sx={row.is_revoked ? { opacity: 0.6 } : undefined}
                  >
                    <TableCell>{row.user_name}</TableCell>
                    <TableCell>{row.course_name}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={row.result === "PASS" ? "success" : "error"}
                        label={row.result === "PASS" ? "通過" : "不通過"}
                      />
                      {row.result_note !== null && row.result_note !== "" && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          備註：{row.result_note}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>{formatDateTime(row.approved_at)}</TableCell>
                    <TableCell>{row.approved_by_name}</TableCell>
                    <TableCell>
                      {row.is_revoked ? (
                        <Box>
                          <Chip size="small" label="已撤銷" />
                          <Typography variant="caption" color="text.secondary" display="block">
                            {row.revoked_by_name} {row.revoked_at === null ? "" : formatDateTime(row.revoked_at)} 撤銷
                            {row.revoke_reason === null ? "" : `｜原因：${row.revoke_reason}`}
                          </Typography>
                        </Box>
                      ) : (
                        <Chip size="small" color="success" variant="outlined" label="有效" />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="caption" color="text.secondary">
              共 {data?.meta.total ?? 0} 筆
            </Typography>
            {totalPages > 1 && <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} />}
          </Stack>
        </>
      )}
    </Stack>
  )
}
