import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline"
import SearchIcon from "@mui/icons-material/Search"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Grid from "@mui/material/Grid"
import MenuItem from "@mui/material/MenuItem"
import Pagination from "@mui/material/Pagination"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { CourseCard } from "./CourseCard"
import { coursesApi } from "./coursesService"
import type { CourseListParams } from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useDebouncedValue } from "../../hooks/useDebouncedValue"
import { usePagedQuery } from "../../hooks/usePagedQuery"

/** 桌機每列三張，四列剛好一頁。 */
const PAGE_SIZE = 12

type Scope = "mine" | "all"

/**
 * ET01 課程列表（US7 / #299）。
 *
 * ## 兩個分頁的狀態過濾**相反**
 *
 * 「我建立的」含草稿與已關閉（教師要管理自己的課）；「全部課程」僅已發布——草稿的存在
 * 對他人是秘密，已關閉者不列入（`FR-ET-US7-01`）。**過濾由後端做**，前端只傳 `scope`。
 *
 * ## 分頁狀態放 URL query
 *
 * 重新整理或把連結貼給同事時不該跳回預設分頁。`?scope=all` 也讓「我剛剛在看全部課程」
 * 這件事在瀏覽器上一頁／下一頁之間成立。
 *
 * ## 兩種空狀態刻意分開
 *
 * 對一個還沒建過任何課程的新教師說「查無符合條件之課程」，會讓他以為自己篩錯了。
 */
export function EtCourseListPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const scope: Scope = searchParams.get("scope") === "all" ? "all" : "mine"

  const [keyword, setKeyword] = useState("")
  const [tagId, setTagId] = useState<number | "">("")
  const [ownerId, setOwnerId] = useState<string | "">("")
  const [page, setPage] = useState(1)

  // 打字時不要每個字元都打一次 API
  const debouncedKeyword = useDebouncedValue(keyword, 300)

  const { data: capabilities } = useQuery({
    queryKey: QUERY_KEYS.etCourses.capabilities(),
    queryFn: coursesApi.getCapabilities,
  })

  const { data: filterTags } = useQuery({
    queryKey: QUERY_KEYS.etCourses.filterTags(),
    // ⚠️ 是 `listFilterTags`（全部含停用者）而**不是** `listTags`（ET02 編輯用、排除停用者）。
    // 用錯會讓掛著已停用標籤的歷史課程搜不到，而畫面上沒有任何異常。
    queryFn: coursesApi.listFilterTags,
  })

  const params: CourseListParams = useMemo(
    () => ({
      scope,
      ...(debouncedKeyword ? { q: debouncedKeyword } : {}),
      ...(tagId !== "" ? { tag_id: tagId } : {}),
      ...(scope === "all" && ownerId !== "" ? { owner_id: ownerId } : {}),
      page,
      limit: PAGE_SIZE,
    }),
    [scope, debouncedKeyword, tagId, ownerId, page],
  )

  const { data, isPending, isError, error } = usePagedQuery(QUERY_KEYS.etCourses.list(params), () =>
    coursesApi.list(params),
  )

  const changeScope = (next: Scope) => {
    setSearchParams(next === "mine" ? {} : { scope: next })
    setPage(1)
    // 切分頁時清掉「建立者」——它只在「全部課程」有意義，留著會讓使用者看到一個空清單
    // 卻找不到原因
    setOwnerId("")
  }

  const hasFilters = debouncedKeyword !== "" || tagId !== "" || ownerId !== ""
  const rows = data?.data
  const courses = rows ?? []
  const totalPages = data?.meta.total_pages ?? 0

  // 「全部課程」的建立者選項取自當前結果——列出沒有課程的教師只會產生「選了必定零筆」
  // 的選項。
  //
  // ⚠️ **選定某位建立者後就不再更新**：那時的結果只剩他一個人，拿去重算會讓選單塌成
  // 單一選項，使用者想改選別人得先切回「全部」再選一次。
  const [ownerOptions, setOwnerOptions] = useState<[string, string][]>([])
  useEffect(() => {
    if (ownerId !== "" || rows === undefined) return
    const seen = new Map<string, string>()
    for (const c of rows) if (!seen.has(c.owner_id)) seen.set(c.owner_id, c.owner_name ?? c.owner_id)
    setOwnerOptions([...seen.entries()])
  }, [rows, ownerId])

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5">課程列表</Typography>
      </Stack>

      <Tabs value={scope} onChange={(_, v: Scope) => changeScope(v)} sx={{ mb: 1 }}>
        <Tab value="mine" label="我建立的" />
        <Tab value="all" label="全部課程" />
      </Tabs>

      {/* 常駐說明，非 Snackbar——它是頁面的持續規則，不是一次性事件 */}
      <Alert severity="info" sx={{ mb: 2 }}>
        點擊<strong>自己建立</strong>之課程進入<strong>編輯模式</strong>；點擊
        <strong>他人建立</strong>之課程進入<strong>檢視模式（唯讀）</strong>，僅可閱覽不可編輯內容。
      </Alert>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2} alignItems="flex-end">
          <Grid size={{ xs: 12, md: 5 }}>
            <TextField
              fullWidth
              size="small"
              label="關鍵字"
              placeholder="課程名稱"
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value)
                setPage(1)
              }}
              slotProps={{ input: { startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1 }} /> } }}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 3 }}>
            <TextField
              select
              fullWidth
              size="small"
              label="受訓單位標籤"
              value={tagId}
              onChange={(e) => {
                setTagId(e.target.value === "" ? "" : Number(e.target.value))
                setPage(1)
              }}
            >
              <MenuItem value="">全部</MenuItem>
              {(filterTags ?? []).map((tag) => (
                <MenuItem key={tag.tag_id} value={tag.tag_id}>
                  {tag.tag_name}
                  {/* 停用標籤仍可篩選（要查得到歷史課程），但標示出來免得教師以為它還能掛 */}
                  {!tag.is_active && "（已停用）"}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          {/* 只在「全部課程」出現；隱藏時**不佔位**，否則搜尋列會空一格 */}
          {scope === "all" && (
            <Grid size={{ xs: 12, md: 2 }}>
              <TextField
                select
                fullWidth
                size="small"
                label="建立者"
                value={ownerId}
                onChange={(e) => {
                  setOwnerId(e.target.value)
                  setPage(1)
                }}
              >
                <MenuItem value="">全部</MenuItem>
                {ownerOptions.map(([id, name]) => (
                  <MenuItem key={id} value={id}>
                    {name}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
          )}
          <Grid size={{ xs: 12, md: scope === "all" ? 2 : 4 }}>
            {capabilities?.can_create_course && (
              <Button
                fullWidth
                variant="contained"
                startIcon={<AddCircleOutlineIcon />}
                onClick={() => navigate("/et/courses/new")}
              >
                新增課程
              </Button>
            )}
          </Grid>
        </Grid>
      </Paper>

      {isError && <Alert severity="error">{(error as Error | null)?.message ?? "課程清單載入失敗"}</Alert>}

      {isPending && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      )}

      {!isPending && !isError && courses.length === 0 && (
        <Paper variant="outlined" sx={{ p: 6, textAlign: "center" }}>
          {hasFilters ? (
            /* ET-MSG-ET01-001 */
            <Typography color="text.secondary">查無符合條件之課程</Typography>
          ) : (
            <Stack spacing={2} alignItems="center">
              <Typography color="text.secondary">
                {scope === "mine" ? "您尚未建立任何課程" : "目前沒有已發布的課程"}
              </Typography>
              {scope === "mine" && capabilities?.can_create_course && (
                <Button variant="outlined" startIcon={<AddCircleOutlineIcon />} onClick={() => navigate("/et/courses/new")}>
                  建立第一門課程
                </Button>
              )}
            </Stack>
          )}
        </Paper>
      )}

      {courses.length > 0 && (
        <>
          <Grid container spacing={3}>
            {courses.map((course) => (
              <Grid key={course.course_id} size={{ xs: 12, sm: 6, md: 4 }}>
                <CourseCard course={course} onOpen={(id) => navigate(`/et/courses/${id}`)} />
              </Grid>
            ))}
          </Grid>
          {totalPages > 1 && (
            <Stack alignItems="center" sx={{ mt: 3 }}>
              <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} />
            </Stack>
          )}
        </>
      )}
    </Box>
  )
}
