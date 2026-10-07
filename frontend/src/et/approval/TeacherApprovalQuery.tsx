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

/**
 * 結果篩選的四態，以及各自對應的**兩個 API 參數**（#548 裁示 6）。
 *
 * 🔴 畫面是單一下拉，但 `result`（`ET_APPROVAL.RESULT`）與 `revoked`（`IS_REVOKED`）
 * 是**正交的兩個維度**——被撤銷的紀錄其 `RESULT` 仍是 `PASS` 或 `FAIL`。
 *
 * ⛔ **不要把這張表壓成單一參數送給後端。** 改制前「僅通過」只送 `result=PASS`、
 * 完全沒有撤銷條件，於是**選「僅通過」會列出已撤銷的通過**——那正是本次要修的缺陷，
 * 成因就是兩個維度被當成一個。
 *
 * ⚠️「僅不通過」也帶 `revoked: false` 是刻意的：撤銷不檢查 `RESULT`，不通過的紀錄
 * 也撤銷得了。既然「僅通過」排除已撤銷，這裡沒有理由不排除。
 */
const RESULT_OPTIONS = [
  { value: "", label: "全部結果", result: undefined, revoked: undefined },
  { value: "PASS", label: "僅通過", result: "PASS", revoked: false },
  { value: "FAIL", label: "僅不通過", result: "FAIL", revoked: false },
  { value: "REVOKED", label: "僅已撤銷", result: undefined, revoked: true },
] as const satisfies readonly {
  value: string
  label: string
  result?: "PASS" | "FAIL"
  revoked?: boolean
}[]

/**
 * 教師 / 管理者視角——依學員**姓名或 Email** 與 / 或**課程**查**受訓完成狀況**（#464 起含
 * 不需線下核可之課程的完課；兩種「通過」畫面上不分辨）
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
 * 「查無符合條件的紀錄」只在**查過之後**出現。一進畫面就顯示它，會讓教師以為
 * 系統已經查過而且真的沒有資料。
 */
export function TeacherApprovalQuery() {
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
    // 下拉的母體是「核可紀錄 ∪ 不需核可課程的完課」（#464），不需要即時——新通過一筆之後
    // 晚五分鐘才出現在篩選選單裡，對「查受訓完成狀況」這件事沒有影響。
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

  // 🔴 ↔️ **這裡原本有一道「兩者皆空就不發請求」的閘（#468），#548 裁示 3 拿掉了。**
  //
  // 它擋的不是能力（教師本來就倒得出全部紀錄），而是「會不會**不小心**看到全院人員
  // 的通過紀錄」；#468 拿掉搜尋按鈕改為輸入即查之後，它就是「你還沒按查詢」的替代品。
  //
  // 推翻它的理由有兩半：
  //
  // 1. **使用者的需求與它直接衝突**：「選了全部課程就該列出所有課程的核可結果」。
  //    而「全部課程」與「全部結果」都是**不篩這個維度**的意思，兩者在下拉裡都是預設值
  //    ——分不出「刻意選了不篩」與「沒動過」，所以保留這道閘等於那個需求做不到。
  // 2. **它的理由（`見 #392`：這類查詢無法偵測誤用）已被補上**：裁示 5 讓不指名的
  //    查詢寫入 `DP_AUDIT_LOG`（`ACTION_TYPE=QUERY`）。從「擋下」改為「留痕」。
  //
  // ⚠️ 代價誠實寫在這裡：**一進畫面就是全部名單**。可接受是因為可見範圍已由裁示 1
  // 統一（沒有「看到不該看的」這回事了），而負面自由文字仍由欄位遮蔽擋著。
  const selected = RESULT_OPTIONS.find((o) => o.value === result) ?? RESULT_OPTIONS[0]

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
        // ⛔ 兩個參數都要送。只送 `result` 會讓「僅通過」列出已撤銷的通過——
        // 見 `RESULT_OPTIONS` 的 🔴。
        result: selected.result,
        revoked: selected.revoked,
        page,
      }),
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
                  ? // ↔️ #548 裁示 4 之前這句依身分分岔（教師版說「您開設的課程」）。
                    // 下拉不分 owner 之後，對教師與管理者都只剩這一種成因。
                    "系統中尚無通過紀錄"
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

      {isPending ? (
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
        // | 全系統還沒有任何通過紀錄 | 需核可課程：去 ET02 核可學員；不需核可課程：等學員完課 |
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
          查無符合條件的紀錄。
          {/* ↔️ 裁示 C 時代這裡對教師多一句「可能不在您的可見範圍內——請洽管理者查詢」。
              可見範圍統一後那句話不再成立：教師看得到的與管理者完全相同，說它會把人
              引去做一件沒有用的事。⚠️ 另外兩種成因（全系統尚無紀錄 / 這個人沒有）
              仍刻意不分，理由見上方表格。 */}
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
                  {/* #464：欄名由「核可時間」改為「通過時間」——不需核可的課程以完課時間計，
                      兩種通過畫面上不區分（裁示）。「核可人」維持原名：需核可課程確實有人核可，
                      不需核可者顯示「—」。 */}
                  <TableCell>通過時間</TableCell>
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
                      {/* 🔴 已撤銷的列**不得顯示綠色「通過」**（#548 裁示 6）。

                          撤銷只設 `IS_REVOKED`，`RESULT` 仍是 `PASS`——改制前這一格
                          只看 `result`，於是一筆已撤銷的通過在「核可結果」欄是綠色的
                          「通過」，只有最右邊的「狀態」欄才寫已撤銷。整列雖有淡化，
                          但一眼掃過去讀到的就是通過。

                          ⚠️ 仍保留原 `RESULT` 的字樣（「原通過」/「原不通過」），不要
                          只寫「已撤銷」——撤銷的是核可這個動作，當初判的是通過還是
                          不通過仍是事實，而「這個人當初有沒有過」是教師會問的問題。 */}
                      <Chip
                        size="small"
                        color={row.is_revoked ? "default" : row.result === "PASS" ? "success" : "error"}
                        variant={row.is_revoked ? "outlined" : "filled"}
                        label={
                          row.is_revoked
                            ? `已撤銷（原${row.result === "PASS" ? "通過" : "不通過"}）`
                            : row.result === "PASS"
                              ? "通過"
                              : "不通過"
                        }
                      />
                      {row.result_note !== null && row.result_note !== "" && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          備註：{row.result_note}
                        </Typography>
                      )}
                    </TableCell>
                    {/* 通過時間為空＝活化前就已完課的既有資料：`formatDateTime(null)` 本身就回「—」，
                        不需另外判斷。核可人為空＝該課程不需線下核可——這一格**沒有**經過任何
                        格式化函式，所以要自己補「—」，否則是一格空白。 */}
                    <TableCell>{formatDateTime(row.approved_at)}</TableCell>
                    <TableCell>{row.approved_by_name ?? "—"}</TableCell>
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
