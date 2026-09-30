import SearchIcon from "@mui/icons-material/Search"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
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
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { useDebouncedValue } from "../../hooks/useDebouncedValue"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"
import { approvalsApi } from "./approvalsService"
import { courseOptionsEmptyReason } from "./courseOptionsState"
import type { ApprovalQueryRow } from "./schemas"

/** 結果篩選的值域。`""` 代表不篩（wireframe 的「全部結果」）。 */
const RESULT_OPTIONS = [
  { value: "", label: "全部結果" },
  { value: "PASS", label: "僅通過" },
  { value: "FAIL", label: "僅不通過" },
] as const

/**
 * 教師 / 管理者視角——依學員**姓名或 Email** 與 / 或**課程**查核可紀錄
 * （`FR-ET-US17-01`、#436、#439）。
 *
 * ⚠️ 姓名與 Email 共用同一個輸入框、擇一命中即可：同名同姓時姓名不足以定位，而 Email
 * 是帳號的唯一鍵。分兩欄會讓「隨便給個識別資訊找到人」這個實際用法變成要先想「我手上
 * 這個是哪種」。
 *
 * ## 關鍵字與課程「至少給一個」（#439）
 *
 * 原本關鍵字必填（SA Q2 裁示 A），但使用者常常**正是不知道有誰可以查**。改為兩者
 * 擇一之後，選課程即可列出該課的核可紀錄。
 *
 * ⚠️ 兩者皆不給仍會被擋——那才是裁示 A 原本要防的「留白查全部」。**換的是手段不是
 * 目的**：課程之所以能取代關鍵字，是因為教師的下拉只有自己開設的課，而看自己課的學員
 * 是他本來就有的資訊（ET02 整頁就是做這件事）。
 *
 * ⛔ 下拉只是 UI——後端另有一道「非管理者只能依自己課程篩選」的閘（403
 * `ET_APPROVAL_007`）。**兩者是一組的**，只做前者等於沒做。
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
  const [courseId, setCourseId] = useState<number | "">("")
  const [result, setResult] = useState("")
  const [page, setPage] = useState(1)

  // 課程下拉（#439）。⚠️ 走 `approvalsApi.listFilterCourses` 而**不是** ET01 的課程清單
  // ——後者的兩個 scope 都不對（`all` 排除已結束課程、`mine` 對管理者是空的），
  // 完整理由見該函式的註解。
  const coursesQuery = useQuery({
    queryKey: QUERY_KEYS.etApprovals.filterCourses(),
    queryFn: () => approvalsApi.listFilterCourses(),
    // 🔴 **必須設 `staleTime`**，這不是效能微調。專案的 QueryClient 是裸的
    // `new QueryClient()`（`main.tsx`），預設 `staleTime: 0` + `refetchOnWindowFocus: true`
    // ——教師每次切回分頁都會重打一次，而本端點與**核可寫入**共用同一個 60/分分桶
    //（見 `approval/router.py` 模組 docstring）。那正是當初把核可從 `et-tracking`
    // 分桶出去要防的事：教師只是多看幾次畫面，就把他真正需要能送出的動作的配額吃掉。
    //
    // 下拉的母體是核可紀錄，不需要即時——新核可一筆之後晚五分鐘才出現在篩選選單裡，
    // 對「查核可紀錄」這件事沒有影響。
    staleTime: 5 * 60 * 1000,
  })
  const options = coursesQuery.data ?? []

  // 🔴 空的下拉有**三種**成因，畫面必須分得出來——說錯比不說更糟（與 ET02 同一條）。
  // 判定抽在 `courseOptionsState.ts`：其中一種情形（先成功、之後背景刷新失敗）在元件
  // 測試裡要真的觸發一次刷新才驗得到，而那個區別正是最容易寫錯的地方。
  //
  // ⚠️ **整包 `coursesQuery` 交出去、不自己挑旗標**——`isError` 在背景刷新失敗時也是
  // true，餵它會讓一個還有可用選項的下拉被停用並宣稱「載入失敗」。那個選擇交給呼叫端
  // 就會變成沒有測試守得住的自由度，故由該函式自己決定看哪一個。
  //
  // ⚠️ `"none"` 底下其實還混著兩件事（「沒開過課」與「開的課還沒有人被核可」），
  // 這裡**刻意不分**：兩者的下一步相同（去 ET02 核可學員），而要分得出來得多一次查詢。
  const emptyReason = courseOptionsEmptyReason(coursesQuery, options.length)

  // 姓名去抖動（#468）：本頁改為輸入即查，逐字元送出會是每個按鍵一次 POST。
  // ⚠️ 該端點為 **POST**（#391 把它從 GET 改過來，避免姓名進 query string / nginx
  // log / Referer），使用者維度限流 60 req/min——350ms 去抖動下正常打字約 1～2 次。
  const debouncedName = useDebouncedValue(nameInput, 350)
  const keyword = debouncedName.trim()

  // 🔴 **兩者皆空時不發請求**（#468；規則來自 #439，原 SA Q2 裁示 A）。
  //
  // ⛔ 不可以靠後端的 422 `ET_APPROVAL_006` 來擋：那道守門是刻意留著的
  // （`query_rules.normalize_search_criteria` 的 docstring：「換手段、保目的」——
  // 放寬的是「用什麼條件」，不是「可不可以不給條件」），但它是**後端**的最後一道。
  // 前端若照送，使用者每清空一次輸入框就打一次必定失敗的 API，而且錯誤訊息會在
  // 打字途中閃爍。
  //
  // ⚠️ 空白字串要先 `.trim()` 才判——`"   "` 等同未填。
  const hasCriteria = keyword !== "" || courseId !== ""

  const {
    data,
    isPending,
    isError,
    error: queryError,
  } = usePagedQuery<ApprovalQueryRow>(
    QUERY_KEYS.etApprovals.search({ keyword, courseId, result, page }),
    () =>
      approvalsApi.search({
        keyword: keyword || undefined,
        course_id: courseId === "" ? undefined : courseId,
        result: (result || undefined) as "PASS" | "FAIL" | undefined,
        page,
      }),
    { enabled: hasCriteria },
  )

  // 條件變動時回第 1 頁——留在第 3 頁會讓新條件的結果看起來是空的（而使用者剛改完
  // 條件，最可能的解讀是「查不到」）。
  //
  // ⚠️ **於 render 期間同步，不放 `useEffect`**：比照 `CourseEditorPage` 的表單初值。
  // 放 effect 會被 ESLint 的 `setState in effect` 擋下，而且會多渲染一次——中間那一幀
  // 是「新條件 + 舊頁碼」，正是要避免的狀態。
  const criteriaKey = `${keyword}|${courseId}|${result}`
  const [lastCriteria, setLastCriteria] = useState(criteriaKey)
  if (lastCriteria !== criteriaKey) {
    setLastCriteria(criteriaKey)
    setPage(1)
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

      {/* 搜尋列——白底區塊，與 DM03「已廢止文件查詢」一致（#436）。
          裸放在灰底上時欄位看起來像懸空的，而下方結果表格有 Paper 框，上下半部
          視覺不一致會讓人以為畫面還沒載完。 */}
      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems="flex-start">
          <TextField
            label="學員姓名或 Email"
            size="small"
            sx={{ minWidth: 260 }}
            value={nameInput}
            helperText="可輸入部分姓名或 Email"
            onChange={(e) => {
              setNameInput(e.target.value)
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
          {/* 課程下拉（#439）——解決「不知道有誰可以查」：選課程就列得出該課的核可紀錄。
              ⚠️ 教師的選項只有自己開設的課（後端限定），管理者不限。 */}
          <TextField
            select
            label="課程"
            size="small"
            sx={{ minWidth: 220 }}
            value={courseId}
            disabled={emptyReason !== null}
            helperText={
              emptyReason === "failed"
                ? "課程清單載入失敗，請重新整理後再試"
                : emptyReason === "none"
                  ? isAdmin
                    ? "系統中尚無核可紀錄"
                    : "您開設的課程尚無核可紀錄"
                  : "不指定學員時可只選課程"
            }
            onChange={(e) => {
              setCourseId(e.target.value === "" ? "" : Number(e.target.value))
            }}
          >
            <MenuItem value="">全部課程</MenuItem>
            {options.map((c) => (
              <MenuItem key={c.course_id} value={c.course_id}>
                {c.course_name}
              </MenuItem>
            ))}
          </TextField>
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
        </Stack>
      </Paper>

      {!hasCriteria ? (
        // 🔴 條件全空時**保持空白**，不列出全部（#468 裁示；理由見 #392）。
        // 教師本來就倒得出全部紀錄（一分鐘約 40 次請求），所以這不是能力控制——
        // 它控制的是「會不會**不小心**看到全院人員的通過紀錄」。
        // ⛔ 日後若覺得「空白畫面沒東西看」而想改成預設列全部，先回讀 #392。
        <Typography variant="body2" color="text.secondary">
          輸入學員姓名或 Email，或選擇課程即可查詢。
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
        // ⚠️ **「查無」有三種成因，而這裡只分得出兩種**（#436）：
        //
        // | 真相 | 該做什麼 |
        // |---|---|
        // | 全系統還沒有任何核可紀錄 | 去 ET02 核可學員 |
        // | 有紀錄，但這個人沒有 | 確認姓名 / 改用 Email 查 |
        // | 有紀錄，但被**可見範圍**擋掉 | 找管理者查 |
        //
        // ⛔ 前兩種**刻意不分**：要分得出「全系統尚無紀錄」需要一個不受可見範圍限制的
        // 判斷依據，而那會洩漏範圍外的存在性——代價大於它解決的困惑。多查一次也沒用，
        // 那次查詢受同一個範圍限制。
        //
        // 🔴 但第三種**必須講**，而且只對教師講：本頁的使用情境是「排班前確認某人受訓
        // 完整與否」，教師看到「查無」會讀成「這個人沒受過訓」。那是方向最危險的假陰性，
        // 而可見範圍分流（SA Q1 裁示 C）讓它在正式使用時一定會發生。
        <Alert severity="info">
          查無符合條件的核可紀錄。
          {!isAdmin && "若確定該學員已受訓，可能是該紀錄不在您的可見範圍內——請洽管理者查詢。"}
        </Alert>
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
